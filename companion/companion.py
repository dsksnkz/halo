#!/usr/bin/python
"""Halo Companion. Native Qt UI, no browser engine or model preload."""
import html
import json
import math
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QUrl
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QIcon, QAction, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QWidget, QMainWindow, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFrame, QSplitter, QTextBrowser,
    QPlainTextEdit, QSystemTrayIcon, QMenu, QSizePolicy)

BASE = 'http://127.0.0.1:8765'
HERE = Path(__file__).resolve().parent
# Taste brief: monochrome native utility, variance 5 / motion 3 / density 4.
# Native Qt controls and QPainter; no marketing-page component framework.
STYLE = '''
QWidget { background:#0b0b0b; color:#eeeeee; font-family:"JetBrains Mono"; font-size:12px; }
QMainWindow { background:#0b0b0b; }
QLabel#brand { font-family:"sans-serif"; font-size:30px; font-weight:600; letter-spacing:2px; }
QLabel#muted { color:#a0a0a0; }
QLabel#heading { font-size:16px; font-weight:600; }
QLabel#status { color:#ddd; padding:8px 14px; background:#181818; border-radius:8px; }
QFrame#surface { background:#101010; border:1px solid #303030; border-radius:16px; }
QFrame#surface QLabel, QFrame#surface QTextBrowser { background:transparent; }
QPushButton { background:#191919; border:1px solid #393939; border-radius:8px; padding:9px 14px; color:#eee; }
QPushButton:hover { background:#292929; border-color:#777; }
QPushButton:pressed { background:#383838; }
QPushButton:focus { border-color:#eee; }
QPushButton:disabled { color:#777; border-color:#242424; }
QPushButton#send { background:#eee; color:#101010; border-color:#eee; font-weight:600; }
QPushButton#send:hover { background:#ccc; }
QPushButton#send:disabled { background:#444; color:#aaa; border-color:#444; }
QPushButton:checked { border-color:#bbb; color:#fff; }
QPlainTextEdit { background:#141414; border:1px solid #393939; border-radius:8px; padding:10px; selection-background-color:#555; }
QPlainTextEdit:focus { border-color:#999; }
QTextBrowser { border:0; background:transparent; selection-background-color:#555; }
QSplitter::handle { background:transparent; width:20px; }
QScrollBar:vertical { width:5px; background:transparent; margin:2px; }
QScrollBar::handle:vertical { background:#444; border-radius:2px; min-height:25px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QMenu { border:1px solid #444; padding:6px; }
QMenu::item { padding:8px 18px; }
QMenu::item:selected { background:#333; }
'''


def label(text, name=None):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


def surface():
    w = QFrame()
    w.setObjectName('surface')
    layout = QVBoxLayout(w)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(16)
    return w, layout


class Composer(QPlainTextEdit):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.window().send_message()
            return
        super().keyPressEvent(event)


class ConnectionMap(QWidget):
    nodes = [
        ('phone', 'PHONE', 'Wi-Fi / USB', .16, .49),
        ('speech', 'WHISPER', 'Speech to text', .30, .08),
        ('halo', 'HALO', 'Local server', .48, .49),
        ('model', 'GEMINI LITE', 'Gemini OpenCode agent', .78, .33),
        ('voice', 'KOKORO', 'Text to speech', .30, .80),
        ('web', 'WEB SEARCH', 'On request', .82, .76),
    ]
    edges = [('phone','halo'), ('speech','halo'), ('halo','model'), ('halo','voice'), ('model','web')]

    def __init__(self, window):
        super().__init__()
        self.host = window
        self.data = {}
        self.selected = 'halo'
        self.positions = {}
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Live service connection map. Click a service for details.')
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.update)

    def set_data(self, data):
        self.data = data
        active = any(data.get('operations', {}).values())
        if active and self.isVisible() and not self.host.reduce_motion.isChecked():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def status(self, key):
        ops = self.data.get('operations', {})
        if key == 'halo':
            return 'Ready' if self.data.get('session_id') else 'Offline'
        if key == 'phone':
            return 'Linked' if self.data.get('device', {}).get('linked') else 'Disconnected'
        if key == 'model':
            return 'Answering' if ops.get('model') else ('Available' if self.data.get('ready') else 'Offline')
        if key == 'speech':
            return 'Transcribing' if ops.get('transcription') else 'On demand'
        if key == 'voice':
            return 'Synthesizing' if ops.get('voice') else 'On demand'
        return 'Searching' if ops.get('search') else 'On demand'

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        self.positions = {key: QPointF(w*x, 14+(h-90)*y) for key, _, _, x, y in self.nodes}
        # Sparse alignment points keep the map legible without a busy wallpaper.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#272727'))
        for x in range(24, w, 32):
            for y in range(16, h, 32):
                p.drawEllipse(QPointF(x,y), .65, .65)
        active = self.data.get('operations', {})
        working = {'speech':bool(active.get('transcription')), 'model':bool(active.get('model')),
                   'voice':bool(active.get('voice')), 'web':bool(active.get('search'))}
        for start, end in self.edges:
            a, b = self.positions[start], self.positions[end]
            path = QPainterPath(a)
            path.cubicTo(QPointF((a.x()+b.x())/2,a.y()), QPointF((a.x()+b.x())/2,b.y()), b)
            running = working.get(start) or working.get(end)
            p.setPen(QPen(QColor('#aaa' if running else '#444'), 1.3 if running else 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if running and not self.host.reduce_motion.isChecked():
                p.setPen(Qt.NoPen)
                p.setBrush(QColor('#fff'))
                p.drawEllipse(path.pointAtPercent((time.monotonic()*.35)%1), 3, 3)
        for key, title, subtitle, _, _ in self.nodes:
            point = self.positions[key]
            selected = key == self.selected
            r = 36 if key == 'halo' else 21
            p.setPen(QPen(QColor('#eee' if selected else '#666'), 1.4 if selected else 1))
            p.setBrush(QColor('#171717' if selected else '#101010'))
            p.drawEllipse(point, r, r)
            p.setPen(QPen(QColor('#eee'), 1.4))
            p.setBrush(Qt.NoBrush)
            if key == 'halo':
                p.drawEllipse(point, 16, 16)
                p.drawEllipse(point, 9, 9)
            else:
                p.drawEllipse(point, 5, 5)
                if self.status(key) in ('Linked','Answering','Transcribing','Synthesizing','Searching'):
                    p.setBrush(QColor('#eee'))
                    p.drawEllipse(point, 3, 3)
            p.setPen(QColor('#eee'))
            p.setFont(QFont('JetBrains Mono', 10, QFont.Medium))
            p.drawText(QRectF(point.x()-80, point.y()+r+12,160,20), Qt.AlignCenter, title)
            p.setPen(QColor('#a0a0a0'))
            p.setFont(QFont('JetBrains Mono', 8))
            p.drawText(QRectF(point.x()-80, point.y()+r+33,160,18), Qt.AlignCenter, self.status(key))
        p.end()

    def mousePressEvent(self, event):
        for key, point in self.positions.items():
            if math.hypot(event.position().x()-point.x(), event.position().y()-point.y()) < 42:
                self.selected = key
                self.host.show_node(key)
                self.update()
                break

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Left,Qt.Key_Up,Qt.Key_Right,Qt.Key_Down):
            keys = [node[0] for node in self.nodes]
            direction = -1 if event.key() in (Qt.Key_Left,Qt.Key_Up) else 1
            self.selected = keys[(keys.index(self.selected)+direction)%len(keys)]
            self.host.show_node(self.selected)
            self.update()
        else:
            super().keyPressEvent(event)


class Companion(QMainWindow):
    def __init__(self, background=False):
        super().__init__()
        self.setWindowTitle('Halo Companion')
        self.setWindowIcon(QIcon(str(HERE/'halo.svg')))
        self.resize(1240, 820)
        self.setMinimumSize(980, 680)
        self.network = QNetworkAccessManager(self)
        self.data = {}
        self.last_chat = None
        self.pending = False
        self.polling = False
        self.session = None
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(22)
        header = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(3)
        brand.addWidget(label('HALO', 'brand'))
        brand.addWidget(label('Companion', 'muted'))
        header.addLayout(brand)
        header.addStretch()
        self.connection = label('Connecting', 'status')
        header.addWidget(self.connection)
        self.hide_button = QPushButton('Hide window')
        self.hide_button.setToolTip('Keep Halo running. Reopen it from your app launcher.')
        self.hide_button.clicked.connect(self.hide_to_tray)
        header.addWidget(self.hide_button)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(20)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.setSpacing(18)
        map_panel, map_layout = surface()
        map_layout.addWidget(label('Connections', 'heading'))
        map_layout.addWidget(label('Live routes between Halo and its services.', 'muted'))
        self.reduce_motion = QPushButton('Motion off')
        self.reduce_motion.setCheckable(True)
        self.reduce_motion.setToolTip('Disable activity animation')
        self.reduce_motion.clicked.connect(lambda: self.graph.set_data(self.data))
        self.graph = ConnectionMap(self)
        map_layout.addWidget(self.graph,1)
        self.node_detail = label('HALO  /  Local server at 127.0.0.1:8765', 'muted')
        self.node_detail.setWordWrap(True)
        map_layout.addWidget(self.node_detail)
        left_layout.addWidget(map_panel,1)
        device_panel, device_layout = surface()
        device_row = QHBoxLayout()
        self.device_name = label('Phone', 'heading')
        device_row.addWidget(self.device_name)
        device_row.addStretch()
        self.open_button = QPushButton('Open on phone')
        self.open_button.clicked.connect(self.open_phone)
        device_row.addWidget(self.open_button)
        device_layout.addLayout(device_row)
        self.device_detail = label('Waiting for Halo over Wi-Fi or USB.', 'muted')
        self.device_detail.setWordWrap(True)
        device_layout.addWidget(self.device_detail)
        self.activity = label('No activity yet.', 'muted')
        self.activity.setWordWrap(True)
        device_layout.addWidget(self.activity)
        left_layout.addWidget(device_panel)
        splitter.addWidget(left)
        chat_panel, chat_layout = surface()
        chat_header = QHBoxLayout()
        chat_header.addWidget(label('Conversation', 'heading'))
        chat_header.addStretch()
        self.clear_button = QPushButton('Clear')
        self.clear_button.clicked.connect(self.clear_chat)
        chat_header.addWidget(self.clear_button)
        chat_layout.addLayout(chat_header)
        self.chat_hint = label('Shared with your phone. Kept in this session.', 'muted')
        self.chat_hint.setWordWrap(True)
        chat_layout.addWidget(self.chat_hint)
        self.permission_panel=QFrame()
        self.permission_layout=QVBoxLayout(self.permission_panel)
        self.permission_layout.setContentsMargins(0,0,0,0)
        self.permission_signature=None
        self.permission_panel.hide()
        chat_layout.addWidget(self.permission_panel)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        self.chat.setAccessibleName('Shared conversation')
        chat_layout.addWidget(self.chat,1)
        self.notice = label('', 'muted')
        self.notice.setWordWrap(True)
        self.notice.hide()
        chat_layout.addWidget(self.notice)
        self.composer = Composer()
        self.composer.setPlaceholderText('Message Halo…')
        self.composer.setFixedHeight(86)
        self.composer.setAccessibleName('Message Halo. Enter sends. Shift Enter adds a line.')
        chat_layout.addWidget(self.composer)
        actions = QHBoxLayout()
        self.web_button = QPushButton('Web on')
        self.web_button.setCheckable(True)
        self.web_button.setChecked(True)
        self.web_button.clicked.connect(lambda on: self.web_button.setText('Web on' if on else 'Web off'))
        actions.addWidget(self.web_button)
        actions.addStretch()
        self.stop_button=QPushButton('Stop agent')
        self.stop_button.clicked.connect(lambda:self.request('/api/agent/cancel',self.action_finished,{}))
        self.stop_button.setEnabled(False)
        actions.addWidget(self.stop_button)
        self.send_button = QPushButton('Send')
        self.send_button.setObjectName('send')
        self.send_button.clicked.connect(self.send_message)
        actions.addWidget(self.send_button)
        chat_layout.addLayout(actions)
        splitter.addWidget(chat_panel)
        splitter.setSizes([690, 440])
        layout.addWidget(splitter,1)
        footer = QHBoxLayout()
        self.model_label = label('OpenCode · Gemini 3.5 Flash-Lite', 'muted')
        footer.addWidget(self.model_label)
        footer.addStretch()
        footer.addWidget(self.reduce_motion)
        footer.addWidget(label('Wi-Fi and USB reconnect automatically', 'muted'))
        layout.addLayout(footer)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1800)
        self.poll_timer.timeout.connect(self.poll)
        self.tray = QSystemTrayIcon(QIcon(str(HERE/'halo.svg')), self)
        self.tray.setToolTip('Halo Companion')
        menu = QMenu()
        show = menu.addAction('Open Halo Companion')
        show.triggered.connect(self.reveal)
        hide = menu.addAction('Hide window')
        hide.triggered.connect(self.hide_to_tray)
        menu.addSeparator()
        quit_action = menu.addAction('Quit companion')
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.render_chat([])
        if not background:
            self.show()

    def request(self, path, callback, body=None, timeout=10000):
        req = QNetworkRequest(QUrl(BASE+path))
        req.setTransferTimeout(timeout)
        if body is None:
            reply = self.network.get(req)
        else:
            req.setHeader(QNetworkRequest.ContentTypeHeader,'application/json')
            reply = self.network.post(req, json.dumps(body).encode())
        def done():
            try:
                raw = bytes(reply.readAll())
                data = json.loads(raw) if raw else {}
                error = data.get('error') or (reply.errorString() if reply.error() != QNetworkReply.NoError else None)
                callback(data, error)
            except Exception as exc:
                callback({}, str(exc))
            finally:
                reply.deleteLater()
        reply.finished.connect(done)

    def poll(self):
        if self.polling or not self.isVisible():
            return
        self.polling = True
        def receive(data, error):
            self.polling = False
            if error:
                self.connection.setText('Server offline')
                self.data = {}
                self.graph.set_data({})
                self.open_button.setEnabled(False)
                self.send_button.setEnabled(False)
                self.device_detail.setText('Halo is restarting or unavailable. Reconnecting automatically.')
                return
            self.data = data
            self.session = data.get('session_id')
            device = data.get('device',{})
            linked = device.get('linked',False)
            self.connection.setText('Phone linked' if linked else 'Phone '+device.get('status','disconnected'))
            self.device_name.setText(device.get('name','Phone'))
            transport='Wi-Fi' if device.get('transport')=='wifi' else 'USB'
            self.device_detail.setText(transport+' connected  ·  '+('Halo app online' if data.get('phone_online') else 'Waiting for Halo') if linked else 'Open Halo on the same Wi-Fi, or connect the USB cable.')
            self.open_button.setEnabled(linked and bool(device.get('serial')))
            self.open_button.setToolTip('Open the Halo app manually when using Wi-Fi without USB.')
            ops = data.get('operations',{})
            busy = bool(ops.get('model')) or self.pending
            self.send_button.setEnabled(not busy and data.get('ready',False))
            self.clear_button.setEnabled(not busy)
            revision = (self.session,data.get('revision'))
            if revision != self.last_chat:
                self.last_chat = revision
                self.render_chat(data.get('messages',[]))
            agent=data.get('agent',{})
            self.chat_hint.setText(agent.get('activity','OpenCode is working…') if busy else 'Shared with your phone. OpenCode can run laptop commands.')
            self.render_permissions(agent.get('permissions',[]))
            self.stop_button.setEnabled(bool(agent.get('busy')))
            self.graph.set_data(data)
            self.show_node(self.graph.selected)
            metrics = data.get('metrics',{})
            response = metrics.get('last_response_ms')
            self.model_label.setText(data.get('model_label','Gemini 3.5 Flash-Lite')+'  ·  '+(f'Last reply {response/1000:.2f}s' if response is not None else 'No inference while idle'))
            recent = data.get('events',[])[:2]
            self.activity.setText('\n'.join(time.strftime('%H:%M',time.localtime(item['time']))+'  '+item['text'] for item in recent) or 'Ready for your first message.')
        self.request('/api/companion',receive)

    def render_chat(self, messages):
        scroll = self.chat.verticalScrollBar()
        at_bottom = scroll.maximum()-scroll.value()<36
        old = scroll.value()
        if not messages:
            self.chat.setHtml('<div style="color:#aaa;margin-top:60px;"><p style="font-size:20px;color:#eee;">Start a conversation.</p><p>Speak to Halo on your phone,<br>or write a message below.</p></div>')
            return
        parts = []
        for message in messages:
            user = message.get('role')=='user'
            content = html.escape(message.get('content','')).replace('\n','<br>')
            sources = []
            for source in message.get('sources',[]):
                url = source.get('url','')
                if url.startswith(('https://','http://')):
                    sources.append('<a style="color:#ccc;" href="'+html.escape(url,quote=True)+'">'+html.escape(source.get('title',url))+'</a>')
            parts.append('<p style="margin-top:22px;color:#999;font-size:10px;">'+('YOU' if user else 'HALO')+'</p><p style="line-height:150%;font-size:13px;color:'+('#bbb' if user else '#f1f1f1')+';">'+content+'</p>'+('<p>'+'<br>'.join(sources)+'</p>' if sources else ''))
        self.chat.setHtml(''.join(parts))
        scroll.setValue(scroll.maximum() if at_bottom else old)

    def show_node(self, key):
        descriptions = {'halo':'Local server · conversation and paired Wi-Fi / USB routing',
                        'phone':'Paired encrypted Wi-Fi · USB fallback · local microphone page',
                        'model':self.data.get('model_label','Gemini 3.5 Flash-Lite')+' · OpenCode agent controls this laptop',
                        'speech':'Whisper small.en · local English transcription',
                        'voice':'Kokoro Michael · local voice synthesis',
                        'web':'Web search · only used when requested or needed'}
        self.node_detail.setText(descriptions[key])

    def send_message(self):
        text = self.composer.toPlainText().strip()
        if not text or self.pending or not self.session or not self.send_button.isEnabled():
            return
        self.pending = True
        self.send_button.setEnabled(False)
        self.notice.hide()
        history = [{'role':m['role'],'content':m['content']} for m in self.data.get('messages',[])][-10:]
        history.append({'role':'user','content':text})
        self.composer.clear()
        self.render_chat(history)
        self.chat_hint.setText('Halo is answering…')
        def finished(data,error):
            self.pending = False
            if error:
                self.notice.setText(error)
                self.notice.show()
                if not self.composer.toPlainText():
                    self.composer.setPlainText(text)
            self.last_chat = None
            self.poll()
        self.request('/api/chat',finished,{'messages':history,'session_id':self.session,'web':self.web_button.isChecked()},timeout=630000)

    def render_permissions(self,pending):
        signature=json.dumps(pending,sort_keys=True)
        if signature==self.permission_signature:return
        self.permission_signature=signature
        while self.permission_layout.count():
            item=self.permission_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.permission_panel.setVisible(bool(pending))
        for request in pending:
            text=label(request['action']+': '+', '.join(request['resources']))
            text.setWordWrap(True)
            self.permission_layout.addWidget(text)
            for title,allow in [('Allow once',True),('Deny',False)]:
                button=QPushButton(title)
                button.clicked.connect(lambda checked=False,rid=request['id'],ok=allow:self.request('/api/agent/permission',self.action_finished,{'id':rid,'allow':ok}))
                self.permission_layout.addWidget(button)

    def clear_chat(self):
        self.request('/api/conversation/clear',self.action_finished,{})

    def open_phone(self):
        self.request('/api/device/open',self.action_finished,{})

    def action_finished(self, data, error):
        if error:
            self.notice.setText(error)
            self.notice.show()
        else:
            self.notice.hide()
        self.poll()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        self.hide()

    def showEvent(self,event):
        super().showEvent(event)
        self.poll_timer.start()
        QTimer.singleShot(0,self.poll)

    def hideEvent(self,event):
        self.poll_timer.stop()
        self.graph.timer.stop()
        super().hideEvent(event)

    def closeEvent(self,event):
        event.ignore()
        self.hide_to_tray()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Halo Companion')
    app.setDesktopFileName('halo-companion')
    app.setQuitOnLastWindowClosed(False)
    server = None
    if '--screenshot' not in sys.argv:
        socket = QLocalSocket()
        socket.connectToServer('halo-companion-' + str(__import__('os').getuid()))
        if socket.waitForConnected(300):
            socket.write(b'show' if '--background' not in sys.argv else b'ping')
            socket.waitForBytesWritten(300)
            return
        server = QLocalServer()
        name = 'halo-companion-' + str(__import__('os').getuid())
        QLocalServer.removeServer(name)
        server.listen(name)
    window = Companion('--background' in sys.argv)
    if server:
        def connected():
            client = server.nextPendingConnection()
            def read():
                if bytes(client.readAll()) == b'show':
                    window.reveal()
                client.disconnectFromServer()
            client.readyRead.connect(read)
            if client.bytesAvailable():
                read()
            client.disconnected.connect(client.deleteLater)
        server.newConnection.connect(connected)
    if '--screenshot' in sys.argv:
        target = sys.argv[sys.argv.index('--screenshot')+1]
        window.show()
        QTimer.singleShot(2500,lambda: (window.grab().save(target),app.quit()))
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
