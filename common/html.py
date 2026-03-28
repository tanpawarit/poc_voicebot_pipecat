def get_html_page(title: str, flow_name: str) -> str:
    return (
        """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>"""
        + title
        + """</title>
<style>
:root {
    --bg: #0a0a0a; --surface: #141414; --surface2: #1e1e1e; --border: #2a2a2a;
    --text: #e5e5e5; --text2: #888; --accent: #3b82f6; --accent-glow: rgba(59,130,246,0.15);
    --green: #22c55e; --red: #ef4444; --orange: #f59e0b;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg);
       color: var(--text); min-height: 100vh; }
.container { max-width: 900px; margin: 0 auto; padding: 40px 24px; }
.header { text-align: center; margin-bottom: 40px; }
.header h1 { font-size: 28px; font-weight: 600; margin-bottom: 6px; }
.header .badge { display: inline-block; padding: 4px 12px; background: var(--surface2);
                 border: 1px solid var(--border); border-radius: 20px; font-size: 12px;
                 color: var(--text2); margin-top: 8px; }

.main-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
             overflow: hidden; }

/* Visualizer area */
.visualizer-area { position: relative; height: 200px; display: flex; align-items: center;
                   justify-content: center; background: linear-gradient(180deg, var(--surface) 0%, var(--bg) 100%); }
.orb { width: 100px; height: 100px; border-radius: 50%; background: var(--border);
       transition: all 0.3s ease; position: relative; }
.orb.listening { background: radial-gradient(circle, var(--accent) 0%, transparent 70%);
                 box-shadow: 0 0 60px var(--accent-glow), 0 0 120px var(--accent-glow); }
.orb.speaking { background: radial-gradient(circle, var(--green) 0%, transparent 70%);
                box-shadow: 0 0 60px rgba(34,197,94,0.2), 0 0 120px rgba(34,197,94,0.1); }
.orb.listening .ring, .orb.speaking .ring { position: absolute; inset: -20px; border-radius: 50%;
    border: 1px solid; animation: ring-pulse 2s ease-in-out infinite; }
.orb.listening .ring { border-color: rgba(59,130,246,0.3); }
.orb.speaking .ring { border-color: rgba(34,197,94,0.3); }
.orb .ring:nth-child(2) { inset: -40px; animation-delay: 0.5s; opacity: 0.5; }
@keyframes ring-pulse { 0%,100% { transform: scale(1); opacity: 0.5; } 50% { transform: scale(1.1); opacity: 1; } }

.canvas-container { position: absolute; bottom: 0; left: 0; right: 0; height: 60px; }
canvas { width: 100%; height: 100%; }

.status-label { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%);
                font-size: 12px; color: var(--text2); text-transform: uppercase; letter-spacing: 1px; }

/* Controls */
.controls { padding: 24px; border-top: 1px solid var(--border); display: flex; align-items: center;
            gap: 12px; flex-wrap: wrap; }
.controls select { flex: 1; min-width: 200px; padding: 10px 14px; background: var(--surface2);
                   border: 1px solid var(--border); border-radius: 8px; color: var(--text);
                   font-size: 14px; outline: none; }
.controls select:focus { border-color: var(--accent); }
.btn { padding: 10px 24px; font-size: 14px; font-weight: 500; border: none; border-radius: 8px;
       cursor: pointer; transition: all 0.2s; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: #2563eb; }
.btn-primary:disabled { background: #1e3a5f; color: #4a7ab5; cursor: not-allowed; }
.btn-danger { background: var(--red); color: #fff; display: none; }
.btn-danger:hover { background: #dc2626; }

/* Info panels */
.panels { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--border); }
.panel { padding: 20px 24px; }
.panel:first-child { border-right: 1px solid var(--border); }
.panel h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text2);
            margin-bottom: 12px; }

/* Status items */
.status-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0;
              font-size: 13px; }
.status-row .label { color: var(--text2); }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.status-dot.green { background: var(--green); box-shadow: 0 0 6px rgba(34,197,94,0.5); }
.status-dot.red { background: var(--red); }
.status-dot.orange { background: var(--orange); box-shadow: 0 0 6px rgba(245,158,11,0.5); }
.status-dot.gray { background: #555; }

/* Events log */
.events { max-height: 160px; overflow-y: auto; }
.event-item { padding: 6px 0; font-size: 12px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }
.event-item .time { color: var(--text2); white-space: nowrap; font-family: monospace; }
.event-item .msg { color: var(--text); }
.events::-webkit-scrollbar { width: 4px; }
.events::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

@media (max-width: 600px) {
    .panels { grid-template-columns: 1fr; }
    .panel:first-child { border-right: none; border-bottom: 1px solid var(--border); }
}
</style>
</head><body>
<div class="container">
    <div class="header">
        <h1>"""
        + title
        + """</h1>
        <div class="badge">"""
        + flow_name
        + """ flow</div>
    </div>

    <div class="main-card">
        <div class="visualizer-area">
            <div class="orb" id="orb">
                <div class="ring"></div>
                <div class="ring"></div>
            </div>
            <div class="canvas-container"><canvas id="waveform"></canvas></div>
            <div class="status-label" id="status-label">ready</div>
        </div>

        <div class="controls">
            <select id="mic-select"><option value="">Loading devices...</option></select>
            <button class="btn btn-primary" id="start-btn" onclick="startBot()">Connect</button>
            <button class="btn btn-danger" id="leave-btn" onclick="leaveCall()">Disconnect</button>
        </div>

        <div class="panels">
            <div class="panel">
                <h3>Status</h3>
                <div class="status-row">
                    <span class="label">Connection</span>
                    <span id="conn-status"><span class="status-dot gray"></span>Disconnected</span>
                </div>
                <div class="status-row">
                    <span class="label">Agent</span>
                    <span id="agent-status"><span class="status-dot gray"></span>Idle</span>
                </div>
                <div class="status-row">
                    <span class="label">Duration</span>
                    <span id="duration">--:--</span>
                </div>
            </div>
            <div class="panel">
                <h3>Events</h3>
                <div class="events" id="events"></div>
            </div>
        </div>
    </div>
</div>

<audio id="bot-audio" autoplay></audio>

<script>
let pc = null;
let localStream = null;
let audioCtx = null;
let analyser = null;
let animFrame = null;
let durationTimer = null;
let startTime = null;

async function loadDevices() {
    const select = document.getElementById('mic-select');
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter(d => d.kind === 'audioinput');
        select.innerHTML = '';
        audioInputs.forEach((device, i) => {
            const opt = document.createElement('option');
            opt.value = device.deviceId;
            opt.textContent = device.label || ('Microphone ' + (i + 1));
            select.appendChild(opt);
        });
    } catch(e) {
        select.innerHTML = '<option value="">Mic access denied</option>';
    }
}
loadDevices();
navigator.mediaDevices.addEventListener('devicechange', loadDevices);

function logEvent(msg) {
    const el = document.getElementById('events');
    const now = new Date().toLocaleTimeString();
    el.innerHTML = '<div class="event-item"><span class="time">' + now + '</span><span class="msg">' + msg + '</span></div>' + el.innerHTML;
}

function setStatus(connHtml, agentHtml) {
    if (connHtml) document.getElementById('conn-status').innerHTML = connHtml;
    if (agentHtml) document.getElementById('agent-status').innerHTML = agentHtml;
}

function setLabel(text) {
    document.getElementById('status-label').textContent = text;
}

function startDuration() {
    startTime = Date.now();
    durationTimer = setInterval(() => {
        const s = Math.floor((Date.now() - startTime) / 1000);
        const m = Math.floor(s / 60);
        document.getElementById('duration').textContent =
            String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    }, 1000);
}

function stopDuration() {
    clearInterval(durationTimer);
    document.getElementById('duration').textContent = '--:--';
}

function setupVisualizer(stream) {
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    const source = audioCtx.createMediaStreamSource(stream);
    source.connect(analyser);

    const canvas = document.getElementById('waveform');
    const ctx = canvas.getContext('2d');
    const bufLen = analyser.frequencyBinCount;
    const data = new Uint8Array(bufLen);

    function draw() {
        animFrame = requestAnimationFrame(draw);
        canvas.width = canvas.offsetWidth * 2;
        canvas.height = canvas.offsetHeight * 2;
        analyser.getByteFrequencyData(data);
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const barW = (canvas.width / bufLen) * 2;
        let x = 0;
        for (let i = 0; i < bufLen; i++) {
            const h = (data[i] / 255) * canvas.height * 0.8;
            const alpha = 0.3 + (data[i] / 255) * 0.7;
            ctx.fillStyle = 'rgba(59, 130, 246, ' + alpha + ')';
            ctx.fillRect(x, canvas.height - h, barW - 1, h);
            x += barW;
        }

        const avg = data.reduce((a, b) => a + b, 0) / bufLen;
        const orb = document.getElementById('orb');
        if (avg > 15) {
            orb.className = 'orb listening';
        }
    }
    draw();
}

async function startBot() {
    const btn = document.getElementById('start-btn');
    const deviceId = document.getElementById('mic-select').value;
    btn.disabled = true;
    setLabel('connecting');
    setStatus('<span class="status-dot orange"></span>Connecting...', null);
    logEvent('Requesting microphone access...');

    try {
        const audioConstraints = deviceId ? { deviceId: { exact: deviceId } } : true;
        localStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints, video: false });
        logEvent('Microphone acquired');
        setupVisualizer(localStream);

        pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        pc.ontrack = (event) => {
            document.getElementById('bot-audio').srcObject = event.streams[0];
            logEvent('Bot audio track received');

            const botCtx = new AudioContext();
            const botSource = botCtx.createMediaStreamSource(event.streams[0]);
            const botAnalyser = botCtx.createAnalyser();
            botAnalyser.fftSize = 256;
            botSource.connect(botAnalyser);
            const botData = new Uint8Array(botAnalyser.frequencyBinCount);

            function checkBot() {
                requestAnimationFrame(checkBot);
                botAnalyser.getByteFrequencyData(botData);
                const avg = botData.reduce((a, b) => a + b, 0) / botData.length;
                const orb = document.getElementById('orb');
                if (avg > 10) {
                    orb.className = 'orb speaking';
                    setLabel('agent speaking');
                    setStatus(null, '<span class="status-dot green"></span>Speaking');
                } else if (orb.className === 'orb speaking') {
                    orb.className = 'orb listening';
                    setLabel('listening');
                    setStatus(null, '<span class="status-dot green"></span>Listening');
                }
            }
            checkBot();
        };

        pc.oniceconnectionstatechange = () => {
            const state = pc.iceConnectionState;
            logEvent('ICE: ' + state);
            if (state === 'connected') {
                setStatus('<span class="status-dot green"></span>Connected',
                          '<span class="status-dot green"></span>Listening');
                setLabel('listening');
                document.getElementById('leave-btn').style.display = 'inline-block';
                startDuration();
                logEvent('Session started');
            } else if (state === 'disconnected' || state === 'failed') {
                logEvent('Connection lost');
                cleanup();
            }
        };

        localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
        logEvent('Signaling with server...');

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        await new Promise((resolve) => {
            if (pc.iceGatheringState === 'complete') { resolve(); return; }
            pc.onicegatheringstatechange = () => {
                if (pc.iceGatheringState === 'complete') resolve();
            };
        });

        const res = await fetch('/api/offer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
        });
        const answer = await res.json();
        await pc.setRemoteDescription(answer);
        logEvent('WebRTC answer received');

    } catch(e) {
        logEvent('Error: ' + e.message);
        setLabel('error');
        setStatus('<span class="status-dot red"></span>Error', null);
        cleanup();
    }
}

function leaveCall() {
    logEvent('User disconnected');
    cleanup();
}

function cleanup() {
    if (pc) { pc.close(); pc = null; }
    if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
    if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null; }
    stopDuration();
    document.getElementById('bot-audio').srcObject = null;
    document.getElementById('orb').className = 'orb';
    document.getElementById('leave-btn').style.display = 'none';
    document.getElementById('start-btn').disabled = false;
    setLabel('ready');
    setStatus('<span class="status-dot gray"></span>Disconnected',
              '<span class="status-dot gray"></span>Idle');
}
</script>
</body></html>"""
    )
