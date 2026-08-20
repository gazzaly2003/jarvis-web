"""
MO MO Web — free, shareable AI voice assistant.
Runs on Streamlit Community Cloud. Voice in/out via the browser,
brain via Groq's free API, natural voice via Microsoft Edge TTS.
"""

import asyncio
import datetime
import io

import edge_tts
import requests
import speech_recognition as sr
import streamlit as st
import streamlit.components.v1 as components
from groq import Groq

# ---------- CONFIG ----------
ASSISTANT_NAME = "MO MO"
CREATOR_NAME = "Gazzaly"
CREATOR_BIO = (
    f"{CREATOR_NAME} is the developer who built me — someone who wanted a free, "
    f"friendly AI assistant that anyone could talk to. Edit CREATOR_BIO in the "
    f"code to say whatever you'd actually like me to tell people about you."
)
# A few natural female neural voices worth trying if you want a different feel:
#   en-US-AvaNeural (warm, natural)   en-US-EmmaNeural (bright, friendly)
#   en-GB-SoniaNeural (British)       en-US-JennyNeural (previous default)
VOICE = "en-US-AvaNeural"
DEFAULT_CITY = "Colombo"
GROQ_MODEL = "openai/gpt-oss-120b"
# -----------------------------

st.set_page_config(page_title=ASSISTANT_NAME, page_icon="🎙️", layout="centered")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_audio_hash" not in st.session_state:
    st.session_state.last_audio_hash = None

client = Groq(api_key=st.secrets["GROQ_API_KEY"])


# ---------------- ANIMATED WAVEFORM (HTML/JS, runs live in the browser) ----------------

_WAVE_TEMPLATE = """
<div style="background:#000000; border-radius:20px; padding:14px 0; display:flex;
            justify-content:center; align-items:center;">
  <canvas id="wave" width="680" height="140"></canvas>
</div>
<script>
  const canvas = document.getElementById('wave');
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, cy = h / 2;
  const ampScale = __AMP__;
  let t = 0;
  function draw() {
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, w, h);
    const step = 4;
    for (let x = 0; x < w; x += step) {
      const ratio = x / w;
      const envelope = Math.sin(ratio * Math.PI);
      const wave = Math.sin(ratio * 11 + t * 2.4) * 0.55 + Math.sin(ratio * 19 - t * 3.1) * 0.35;
      const barH = Math.max(2, Math.abs(envelope * wave) * ampScale * (h / 2 - 6));
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
        components.html(html, height=170)


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
    # Be forgiving if the user says "Hey Mo Mo" out of habit — just strip it,
    # no wake word is actually needed here since recording is manual.
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


# ---------------- VOICE ----------------

async def _synthesize(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, VOICE)
    audio = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return audio


def speak(text: str) -> bytes:
    return asyncio.run(_synthesize(text))


def transcribe(audio_bytes: bytes):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = r.record(source)
        return r.recognize_google(audio)
    except (sr.UnknownValueError, sr.RequestError):
        return None


# ---------------- UI ----------------

st.title(f"🎙️ {ASSISTANT_NAME}")
st.caption("Your free AI voice assistant")

wave_placeholder = st.empty()
render_waveform(wave_placeholder, "idle")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


def handle_new_message(text: str):
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.write(text)
    render_waveform(wave_placeholder, "thinking")
    with st.spinner("Thinking..."):
        reply = get_reply(text)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.write(reply)
    render_waveform(wave_placeholder, "speaking")
    with st.spinner("Generating voice..."):
        try:
            mp3_bytes = speak(reply)
            st.audio(mp3_bytes, format="audio/mp3", autoplay=True)
        except Exception as e:
            st.warning(f"Voice playback failed: {e}")
    render_waveform(wave_placeholder, "idle")


audio_value = st.audio_input("Tap to record, tap again to stop")

if audio_value is not None:
    audio_bytes = audio_value.getvalue()
    audio_hash = hash(audio_bytes)
    if audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        with st.spinner("Transcribing..."):
            text = transcribe(audio_bytes)
        if text:
            handle_new_message(text)
        else:
            st.warning("Couldn't quite understand that — try again, a bit closer to the mic.")

typed = st.chat_input("...or type your message")
if typed:
    handle_new_message(typed)
