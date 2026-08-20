"""
MO MO Web — free, shareable AI voice assistant.
Click the waveform itself to start listening continuously; click it again
to stop. Matches the desktop app's clean layout — no extra buttons, no
visible audio player, just the waveform, status text, replies, and a
typed-message box.
"""

import asyncio
import base64
import datetime
import time

import edge_tts
import requests
import streamlit as st
import streamlit.components.v1 as components
from groq import Groq
from streamlit_javascript import st_javascript

# ---------- CONFIG ----------
ASSISTANT_NAME = "MO MO"
CREATOR_NAME = "Gazzaly"
CREATOR_BIO = (
    f"{CREATOR_NAME} is the developer who built me — someone who wanted a free, "
    f"friendly AI assistant that anyone could talk to. Edit CREATOR_BIO in the "
    f"code to say whatever you'd actually like me to tell people about you."
)
VOICE = "en-US-AvaNeural"
DEFAULT_CITY = "Colombo"
GROQ_MODEL = "openai/gpt-oss-120b"
# -----------------------------

st.set_page_config(page_title=ASSISTANT_NAME, page_icon="🎙️", layout="centered")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "listening" not in st.session_state:
    st.session_state.listening = False

client = Groq(api_key=st.secrets["GROQ_API_KEY"])


# ---------------- ANIMATED WAVEFORM ----------------

_WAVE_TEMPLATE = """
<div style="background:#0c0c0c; border-radius:999px; padding:10px 0; display:flex;
            justify-content:center; align-items:center; border:1px solid #1f1f1f;">
  <canvas id="wave" width="380" height="64"></canvas>
</div>
<script>
  const canvas = document.getElementById('wave');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, cy = h / 2;
  const ampScale = __AMP__;
  let t = 0;
  function draw() {
    ctx.fillStyle = '#0c0c0c';
    ctx.fillRect(0, 0, w, h);
    const step = 4;
    for (let x = 0; x < w; x += step) {
      const ratio = x / w;
      const envelope = Math.sin(ratio * Math.PI);
      const wave = Math.sin(ratio * 11 + t * 2.4) * 0.55 + Math.sin(ratio * 19 - t * 3.1) * 0.35;
      const barH = Math.max(2, Math.abs(envelope * wave) * ampScale * (h / 2 - 4));
      const hue = (ratio * 280 + t * 25) % 360;
      ctx.strokeStyle = `hsl(${hue}, 85%, 60%)`;
      ctx.lineWidth = step - 1;
      ctx.beginPath();
      ctx.moveTo(x, cy - barH);
      ctx.lineTo(x, cy + barH);
      ctx.stroke();
    }
    t += 0.05;
    requestAnimationFrame(draw);
  }
  draw();
</script>
"""
_AMP_BY_STATUS = {"idle": 0.22, "listening": 1.0, "thinking": 0.4, "speaking": 0.9}


def render_waveform(placeholder, status: str = "idle"):
    html = _WAVE_TEMPLATE.replace("__AMP__", str(_AMP_BY_STATUS.get(status, 0.3)))
    with placeholder.container():
        components.html(html, height=90)


# ---------------- BROWSER SPEECH RECOGNITION ----------------

_LISTEN_JS = """
await new Promise((resolve) => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { resolve("__UNSUPPORTED__"); return; }
    const recognition = new SR();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    let done = false;
    recognition.onresult = (event) => {
        done = true;
        resolve(event.results[0][0].transcript);
    };
    recognition.onerror = () => { if (!done) { done = true; resolve(""); } };
    recognition.onend = () => { if (!done) { done = true; resolve(""); } };
    recognition.start();
});
"""


# ---------------- SKILLS ----------------

def get_time() -> str:
    now = datetime.datetime.now().strftime("%I:%M %p")
    return f"It's {now} on the server — that may not match your local time zone."


def get_weather(city: str = DEFAULT_CITY) -> str:
    try:
        r = requests.get(f"https://wttr.in/{city}?format=%C+%t", timeout=5)
        r.raise_for_status()
        return f"The weather in {city} is {r.text.strip()}"
    except Exception:
        return "Sorry, I couldn't fetch the weather right now."


IDENTITY_PHRASES = [
    "who built you", "who made you", "who created you", "who is your creator",
    "who developed you", "who designed you", "your creator", "your maker",
]

SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, a witty but genuinely helpful AI assistant, speaking "
    "to many different people through a shared website. Be warm and conversational, "
    "and answer any question you're asked to the best of your ability — general "
    "knowledge, advice, casual chat, all of it. Keep answers reasonably short since "
    "they are read aloud. Do NOT mention who built you or your creator unless the "
    "user directly asks a question like 'who built/made/created you'. Never bring "
    "it up on your own, in greetings, or in unrelated answers. You cannot open apps "
    "or control anyone's device — if asked, explain that this web version can only "
    "chat, check the weather, and tell the time."
)


def ask_groq(prompt: str) -> str:
    try:
        history = st.session_state.messages[-10:]
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history +
                     [{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Sorry, I couldn't reach the AI service right now: {e}"


def get_reply(command: str) -> str:
    lower = command.lower().strip()
    for prefix in ("hey mo mo", "hey momo", "mo mo", "momo"):
        if lower.startswith(prefix):
            lower = lower[len(prefix):].strip(" ,.")
            break
    if not lower:
        return "I'm listening — go ahead and ask me something!"
    if any(p in lower for p in IDENTITY_PHRASES):
        return f"I was built by {CREATOR_NAME}. {CREATOR_BIO}"
    elif "weather" in lower:
        return get_weather()
    elif "what time" in lower or lower == "time":
        return get_time()
    else:
        return ask_groq(lower)


# ---------------- VOICE OUTPUT (hidden, autoplay — no visible player) ----------------

async def _synthesize(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, VOICE)
    audio = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return audio


def speak(text: str) -> bytes:
    return asyncio.run(_synthesize(text))


def play_audio_hidden(mp3_bytes: bytes):
    b64 = base64.b64encode(mp3_bytes).decode()
    html = f"""
    <audio autoplay style="display:none">
        <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
    </audio>
    """
    components.html(html, height=0)


# ---------------- UI ----------------

st.markdown(f"<h1 style='text-align:center;'>{ASSISTANT_NAME}</h1>", unsafe_allow_html=True)

status_placeholder = st.empty()
status_placeholder.markdown(
    "<p style='text-align:center; color:#9a9a9a;'>Tap the wave to talk</p>",
    unsafe_allow_html=True,
)

wave_placeholder = st.empty()
render_waveform(wave_placeholder, "listening" if st.session_state.listening else "idle")

btn_col = st.columns([1, 2, 1])[1]
with btn_col:
    btn_label = "⏹  Tap to Stop" if st.session_state.listening else "🎙  Tap to Talk"
    if st.button(btn_label, use_container_width=True,
                 type="primary" if st.session_state.listening else "secondary"):
        st.session_state.listening = not st.session_state.listening
        st.rerun()

for msg in st.session_state.messages:
    avatar = "🧑" if msg["role"] == "user" else "🎙️"
    with st.chat_message(msg["role"], avatar=avatar):
        st.write(msg["content"])


def handle_new_message(text: str):
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user", avatar="🧑"):
        st.write(text)
    render_waveform(wave_placeholder, "thinking")
    status_placeholder.markdown(
        "<p style='text-align:center; color:#9a9a9a;'>Thinking...</p>", unsafe_allow_html=True)
    reply = get_reply(text)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant", avatar="🎙️"):
        st.write(reply)
    render_waveform(wave_placeholder, "speaking")
    status_placeholder.markdown(
        "<p style='text-align:center; color:#9a9a9a;'>Speaking...</p>", unsafe_allow_html=True)
    try:
        mp3_bytes = speak(reply)
        play_audio_hidden(mp3_bytes)
    except Exception:
        pass


# ---- Continuous voice mode ----
if st.session_state.listening:
    status_placeholder.markdown(
        "<p style='text-align:center; color:#ff8ea0;'>Listening... tap the wave to stop</p>",
        unsafe_allow_html=True,
    )
    heard = st_javascript(_LISTEN_JS)
    if heard == "__UNSUPPORTED__":
        st.error("Your browser doesn't support live speech recognition. Try Chrome or Edge.")
        st.session_state.listening = False
    elif heard:
        handle_new_message(heard)
    if st.session_state.listening:
        status_placeholder.markdown(
            "<p style='text-align:center; color:#ff8ea0;'>Listening... tap the wave to stop</p>",
            unsafe_allow_html=True,
        )
        time.sleep(0.2)
        st.rerun()

# ---- Typed chat, always available ----
typed = st.chat_input("...or type here")
if typed:
    handle_new_message(typed)
