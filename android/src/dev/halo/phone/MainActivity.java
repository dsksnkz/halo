package dev.halo.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.webkit.CookieManager;
import org.json.JSONObject;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.util.Arrays;

public final class MainActivity extends Activity {
    private static final String HOME = "http://127.0.0.1:8766/?app=android";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView web;
    private PhoneLink link;
    private PhoneLink.Listener linkListener;
    private boolean linkOnline;
    private LinearLayout disconnected;
    private PermissionRequest pendingPermission;
    private boolean permissionDialog;
    private boolean resumed;
    private boolean failed;
    private final Runnable retry = () -> { if (resumed && failed) web.loadUrl(HOME); };

    private static boolean trusted(Uri uri) {
        return "http".equals(uri.getScheme()) && "127.0.0.1".equals(uri.getHost()) && uri.getPort() == 8766;
    }

    private boolean microphoneAllowed() {
        return checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    private TextView text(String value, int size) {
        TextView label = new TextView(this);
        label.setText(value); label.setTextColor(Color.WHITE); label.setTextSize(size);
        label.setGravity(Gravity.CENTER); label.setPadding(24,12,24,12);
        label.setTypeface(android.graphics.Typeface.MONOSPACE);
        return label;
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        FrameLayout root = new FrameLayout(this); root.setBackgroundColor(Color.BLACK);
        web = new WebView(this); web.setBackgroundColor(Color.BLACK);
        root.addView(web,new FrameLayout.LayoutParams(-1,-1));
        disconnected = new LinearLayout(this); disconnected.setOrientation(LinearLayout.VERTICAL);
        disconnected.setGravity(Gravity.CENTER); disconnected.setBackgroundColor(Color.BLACK);
        disconnected.addView(text("HALO",32));
        disconnected.addView(text("Connect to the same Wi-Fi as your laptop.\nOpen Halo Companion. USB also works.",14));
        Button again = new Button(this); again.setText("RETRY");
        again.setOnClickListener(v -> web.loadUrl(HOME)); disconnected.addView(again);
        root.addView(disconnected,new FrameLayout.LayoutParams(-1,-1));
        setContentView(root); immersive();
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString()+" HaloAndroid/1.1");
        web.addJavascriptInterface(new NativeBridge(),"HaloNative");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (trusted(request.getUrl())) return false;
                String scheme = request.getUrl().getScheme();
                if (request.isForMainFrame() && request.hasGesture() && ("https".equals(scheme)||"http".equals(scheme))) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl())); } catch (Exception ignored) {}
                }
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (trusted(request.getUrl())) return null;
                String scheme = request.getUrl().getScheme();
                if ("data".equals(scheme)||"blob".equals(scheme)||"about".equals(scheme)) return null;
                return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;
                failed = true; disconnected.setVisibility(View.VISIBLE);
                handler.removeCallbacks(retry); handler.postDelayed(retry,3000);
            }
            @Override public void onReceivedHttpError(WebView view,WebResourceRequest request,WebResourceResponse response) {
                if(request.isForMainFrame()&&response.getStatusCode()>=400){failed=true;disconnected.setVisibility(View.VISIBLE);handler.removeCallbacks(retry);handler.postDelayed(retry,3000);}
            }
            @Override public void onPageFinished(WebView view,String url) {
                if (!trusted(Uri.parse(url))) return;
                view.evaluateJavascript("Boolean(document.querySelector('#dashboard'))", result -> {
                    if (!"true".equals(result)) return;
                    failed=false; handler.removeCallbacks(retry); disconnected.setVisibility(View.GONE);
                    Log.i("Halo","Dashboard ready");
                    if (resumed && microphoneAllowed()) resumePage();
                });
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    if (!trusted(request.getOrigin()) || !Arrays.asList(request.getResources()).contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) {
                        request.deny(); return;
                    }
                    if (microphoneAllowed()) { request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); return; }
                    if (pendingPermission!=null) pendingPermission.deny();
                    pendingPermission=request; askMicrophone();
                });
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) {
                if (pendingPermission==request) pendingPermission=null;
            }
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if (message.messageLevel()==ConsoleMessage.MessageLevel.ERROR)
                    Log.w("Halo","Web error at "+message.sourceId()+":"+message.lineNumber());
                return true;
            }
        });
        try {
            linkListener=(online,transport) -> runOnUiThread(() -> {
                linkOnline=online;
                Log.i("Halo","Link "+(online?transport:"reconnecting"));
                if(!online){failed=true;disconnected.setVisibility(View.VISIBLE);return;}
                if(failed){web.evaluateJavascript("window.dispatchEvent(new Event('halo-native-pause'))",null);web.loadUrl(HOME);}
                else if(resumed)web.evaluateJavascript("window.dispatchEvent(new Event('halo-native-network'))",null);
            });
            link=PhoneLink.acquire(this,linkListener);
            CookieManager.getInstance().setCookie(HOME,"HaloLocal="+link.localToken+"; Path=/; HttpOnly; SameSite=Strict");
        }catch(Exception e){Log.e("Halo","Local connection could not start");}
        web.loadUrl(HOME);
        pairingIntent(getIntent());
        if (!microphoneAllowed() && !getPreferences(MODE_PRIVATE).getBoolean("micAsked",false)) askMicrophone();
    }

    private void pairingIntent(Intent intent) {
        String encoded=intent.getStringExtra("halo_pair");if(encoded==null||link==null)return;
        intent.removeExtra("halo_pair");
        try {
            final JSONObject config=new JSONObject(encoded);
            String pin=config.getString("fingerprint");
            if(!pin.matches("[a-f0-9]{64}"))return;
            new AlertDialog.Builder(this).setTitle("Pair Halo with your laptop?")
                .setMessage(config.getString("name")+"\n"+config.getString("host")+"\n\nLaptop fingerprint\n"+pin.substring(0,16)+"…\n\nThis laptop will receive your voice requests and run your commands.")
                .setNegativeButton("Cancel",(dialog,which)->{})
                .setPositiveButton("Pair",(dialog,which)->{try{link.pair(config);}catch(Exception e){Log.w("Halo","Pairing data rejected");}}).show();
        }catch(Exception ignored){}
    }
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);pairingIntent(intent);}

    private void askMicrophone() {
        if (permissionDialog) return;
        permissionDialog=true; getPreferences(MODE_PRIVATE).edit().putBoolean("micAsked",true).apply();
        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},21);
    }

    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if (code!=21) return;
        permissionDialog=false;
        if (pendingPermission!=null) {
            if (microphoneAllowed()) pendingPermission.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else pendingPermission.deny();
            pendingPermission=null;
        }
        if (microphoneAllowed()) { Log.i("Halo","Microphone permission granted"); if(resumed) resumePage(); }
    }

    private void resumePage() {
        web.evaluateJavascript("window.dispatchEvent(new Event('halo-native-resume'))",null);
    }
    @Override public void onResume() {
        super.onResume(); resumed=true; if(web!=null){web.onResume(); if(microphoneAllowed())resumePage();}
        immersive(); if(failed){handler.removeCallbacks(retry);handler.postDelayed(retry,500);}
    }
    @Override public void onPause() {
        resumed=false; handler.removeCallbacks(retry);
        if(web!=null){web.evaluateJavascript("window.dispatchEvent(new Event('halo-native-pause'))",null);web.onPause();}
        super.onPause();
    }
    @Override public void onWindowFocusChanged(boolean focus) {super.onWindowFocusChanged(focus);if(focus)immersive();}
    @Override public void onConfigurationChanged(Configuration config) {super.onConfigurationChanged(config);immersive();}
    @Override public void onBackPressed() {moveTaskToBack(true);}
    @Override public void onDestroy() {
        if(linkListener!=null)PhoneLink.release(linkListener);
        handler.removeCallbacksAndMessages(null); if(pendingPermission!=null)pendingPermission.deny();
        if(web!=null){web.removeJavascriptInterface("HaloNative");web.destroy();}
        super.onDestroy();
    }

    public final class NativeBridge {
        private long lastPulse;
        @JavascriptInterface public synchronized void haptic() {
            long now=SystemClock.uptimeMillis(); if(now-lastPulse<150)return; lastPulse=now;
            if(Settings.System.getInt(getContentResolver(),Settings.System.HAPTIC_FEEDBACK_ENABLED,1)==0)return;
            Vibrator vibrator=(Vibrator)getSystemService(VIBRATOR_SERVICE);
            if(vibrator!=null && vibrator.hasVibrator()) {
                vibrator.vibrate(VibrationEffect.createOneShot(35,VibrationEffect.DEFAULT_AMPLITUDE),
                    new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION).build());
            }
        }
        @JavascriptInterface public void fullscreen() {runOnUiThread(() -> immersive());}
    }
}
