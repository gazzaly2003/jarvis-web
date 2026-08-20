```python
"""
MO MO Web — free, shareable AI voice assistant.

Fixed version:
- Mobile-friendly voice output
- Audio unlock for phones
- Edge TTS voice
- Continuous voice conversation
- Browser speech recognition
- Typed chat still available
- Prevents immediate rerun from killing audio
"""

import asyncio
import base64
import datetime
import html
import re
import time

import edge_tts
import requests
import streamlit as st
import streamlit.components.v1 as components
from groq import Groq
from streamlit_javascript import st_javascript


# ============================================================
# CONFIG
# ============================================================

ASSISTANT_NAME = "MOMO"
CREATOR_NAME = "Gazzaly"

CREATOR_BIO = (
    f"{CREATOR_NAME} is the developer who built me — someone who wanted a free, "
    f"friendly AI assistant that anyone could talk to."
)

VOICE = "en-US-AvaNeural"
DEFAULT_CITY = "Colombo"
GROQ_MODEL = "openai/gpt-oss-120b"


# ============================================================
# STREAMLIT CONFIG
# ============================================================

st.set_page_config(
    page_title=ASSISTANT_NAME,
    page_icon="🎙️",
    layout="centered",
)


# ============================================================
# SESSION STATE
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "listening" not in st.session_state:
    st.session_state.listening = False

if "audio_unlocked" not in st.session_state:
    st.session_state.audio_unlocked = False

if "last_audio" not in st.session_state:
    st.session_state.last_audio = None

if "speaking" not in st.session_state:
    st.session_state.speaking = False


# ============================================================
# GROQ
# ============================================================

client = Groq(
    api_key=st.secrets["GROQ_API_KEY"]
)


# ============================================================
# ANIMATED WAVEFORM
# ============================================================

_WAVE_TEMPLATE = """
<div style="
    background:#0c0c0c;
    border-radius:999px;
    padding:10px 0;
    display:flex;
    justify-content:center;
    align-items:center;
    border:1px solid #1f1f1f;
">
    <canvas id="wave" width="380" height="64"></canvas>
</div>

<script>
const canvas = document.getElementById('wave');
const ctx = canvas.getContext('2d');

const w = canvas.width;
const h = canvas.height;
const cy = h / 2;

const ampScale = __AMP__;

let t = 0;

function draw() {

    ctx.fillStyle = '#0c0c0c';
    ctx.fillRect(0, 0, w, h);

    const step = 4;

    for (let x = 0; x < w; x += step) {

        const ratio = x / w;

        const envelope = Math.sin(ratio * Math.PI);

        const wave =
            Math.sin(ratio * 11 + t * 2.4) * 0.55 +
            Math.sin(ratio * 19 - t * 3.1) * 0.35;

        const barH = Math.max(
            2,
            Math.abs(envelope * wave) *
            ampScale *
            (h / 2 - 4)
        );

        const hue = (ratio * 280 + t * 25) % 360;

        ctx.strokeStyle =
            `hsl(${hue}, 85%, 60%)`;

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


_AMP_BY_STATUS = {
    "idle": 0.22,
    "listening": 1.0,
    "thinking": 0.4,
    "speaking": 0.9,
}


def render_waveform(placeholder, status="idle"):

    amp = _AMP_BY_STATUS.get(status, 0.3)

    html_code = _WAVE_TEMPLATE.replace(
        "__AMP__",
        str(amp)
    )

    with placeholder.container():
        components.html(
            html_code,
            height=90
        )


# ============================================================
# MOBILE AUDIO UNLOCK
# ============================================================

def unlock_audio():

    """
    Creates a tiny audio element and plays it from a user action.

    This helps mobile browsers allow later audio playback.
    """

    unlock_html = """
    <script>

    try {

        const AudioContext =
            window.AudioContext ||
            window.webkitAudioContext;

        if (AudioContext) {

            const ctx = new AudioContext();

            if (ctx.state === "suspended") {
                ctx.resume();
            }

            // Tiny silent buffer.
            const buffer =
                ctx.createBuffer(1, 1, 22050);

            const source =
                ctx.createBufferSource();

            source.buffer = buffer;
            source.connect(ctx.destination);

            source.start(0);
        }

    } catch (e) {
        console.log("Audio unlock:", e);
    }

    </script>
    """

    components.html(
        unlock_html,
        height=1
    )


# ============================================================
# SPEECH RECOGNITION
# ============================================================

_LISTEN_JS = """
await new Promise((resolve) => {

    const SR =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (!SR) {
        resolve("__UNSUPPORTED__");
        return;
    }

    const recognition = new SR();

    recognition.lang = "en-US";

    recognition.interimResults = false;

    recognition.continuous = false;

    recognition.maxAlternatives = 1;

    let finished = false;

    function finish(value) {

        if (finished) return;

        finished = true;

        resolve(value);
    }

    recognition.onresult = (event) => {

        const transcript =
            event.results[0][0].transcript;

        finish(transcript);
    };

    recognition.onerror = (event) => {

        console.log(
            "Speech recognition error:",
            event.error
        );

        finish("");
    };

    recognition.onend = () => {

        if (!finished) {
            finish("");
        }
    };

    try {

        recognition.start();

    } catch (error) {

        console.log(
            "Recognition start error:",
            error
        );

        finish("");
    }

});
"""


# ============================================================
# SKILLS
# ============================================================

def get_time():

    now = datetime.datetime.now().strftime("%I:%M %p")

    return (
        f"It's {now} on the server. "
        "That may not match your local time zone."
    )


def get_weather(city=DEFAULT_CITY):

    try:

        r = requests.get(
            f"https://wttr.in/{city}?format=%C+%t",
            timeout=5
        )

        r.raise_for_status()

        return (
            f"The weather in {city} is "
            f"{r.text.strip()}"
        )

    except Exception:

        return (
            "Sorry, I couldn't fetch the weather right now."
        )


# ============================================================
# AI
# ============================================================

IDENTITY_PHRASES = [
    "who built you",
    "who made you",
    "who created you",
    "who is your creator",
    "who developed you",
    "who designed you",
    "your creator",
    "your maker",
]


SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, a witty but genuinely helpful AI assistant. "
    "Be warm, friendly and conversational. "
    "Answer questions to the best of your ability. "
    "Keep answers reasonably short because your responses are spoken aloud. "
    "Do not mention your creator unless the user directly asks. "
    "Do not claim you can control the user's device. "
    "You can chat, answer questions, check weather and tell the time."
)


def ask_groq(prompt):

    try:

        history = st.session_state.messages[-10:]

        response = client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                }
            ]
            + history
            + [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        )

        return response.choices[0].message.content

    except Exception as e:

        return (
            "Sorry, I couldn't reach the AI service "
            f"right now: {e}"
        )


def get_reply(command):

    lower = command.lower().strip()

    # Remove wake word
    for prefix in (
        "hey mo mo",
        "hey momo",
        "mo mo",
        "momo"
    ):

        if lower.startswith(prefix):

            lower = lower[
                len(prefix):
            ].strip(" ,.")

            break

    if not lower:

        return (
            "I'm listening. "
            "Go ahead and ask me something!"
        )

    if any(
        phrase in lower
        for phrase in IDENTITY_PHRASES
    ):

        return (
            f"I was built by {CREATOR_NAME}. "
            f"{CREATOR_BIO}"
        )

    elif "weather" in lower:

        return get_weather()

    elif (
        "what time" in lower
        or lower == "time"
    ):

        return get_time()

    else:

        return ask_groq(lower)


# ============================================================
# EDGE TTS
# ============================================================

async def _synthesize(text):

    communicate = edge_tts.Communicate(
        text,
        VOICE
    )

    audio = b""

    async for chunk in communicate.stream():

        if chunk["type"] == "audio":

            audio += chunk["data"]

    return audio


def speak(text):

    return asyncio.run(
        _synthesize(text)
    )


# ============================================================
# BROWSER AUDIO PLAYER
# ============================================================

def play_audio(mp3_bytes):

    if not mp3_bytes:
        return

    b64 = base64.b64encode(
        mp3_bytes
    ).decode()

    audio_html = f"""
    <audio
        id="momoAudio"
        autoplay
        playsinline
        preload="auto"
        style="display:none;"
    >
        <source
            src="data:audio/mpeg;base64,{b64}"
            type="audio/mpeg"
        >
    </audio>

    <script>

    const audio =
        document.getElementById("momoAudio");

    if (audio) {

        audio.volume = 1.0;

        audio.play()
            .then(() => {
                console.log("MOMO audio playing");
            })
            .catch((error) => {

                console.log(
                    "Autoplay blocked:",
                    error
                );

                /*
                 * Fallback:
                 * use browser speech synthesis.
                 */
                try {

                    const text =
                        ${repr("")};

                } catch (e) {}

            });
    }

    </script>
    """

    components.html(
        audio_html,
        height=1
    )


# ============================================================
# UI
# ============================================================

st.markdown(
    f"""
    <h1 style="text-align:center;">
        {ASSISTANT_NAME}
    </h1>
    """,
    unsafe_allow_html=True
)


status_placeholder = st.empty()

status_placeholder.markdown(
    """
    <p style="
        text-align:center;
        color:#9a9a9a;
    ">
        Tap the button to talk
    </p>
    """,
    unsafe_allow_html=True
)


wave_placeholder = st.empty()

render_waveform(
    wave_placeholder,
    "listening"
    if st.session_state.listening
    else "idle"
)


# ============================================================
# TALK BUTTON
# ============================================================

btn_col = st.columns(
    [1, 2, 1]
)[1]

with btn_col:

    if st.session_state.listening:

        btn_label = "⏹  Stop Listening"

    else:

        btn_label = "🎙  Tap to Talk"


    if st.button(
        btn_label,
        use_container_width=True,
        type="primary"
        if st.session_state.listening
        else "secondary",
    ):

        # IMPORTANT:
        # This click is a real user interaction.
        # We use it to unlock mobile audio.

        unlock_audio()

        st.session_state.audio_unlocked = True

        st.session_state.listening = (
            not st.session_state.listening
        )

        st.rerun()


# ============================================================
# CHAT HISTORY
# ============================================================

for msg in st.session_state.messages:

    avatar = (
        "🧑"
        if msg["role"] == "user"
        else "🎙️"
    )

    with st.chat_message(
        msg["role"],
        avatar=avatar
    ):

        st.write(
            msg["content"]
        )


# ============================================================
# HANDLE MESSAGE
# ============================================================

def handle_new_message(text):

    text = text.strip()

    if not text:
        return


    # --------------------------------------------------------
    # USER MESSAGE
    # --------------------------------------------------------

    st.session_state.messages.append(
        {
            "role": "user",
            "content": text
        }
    )


    with st.chat_message(
        "user",
        avatar="🧑"
    ):

        st.write(text)


    # --------------------------------------------------------
    # THINKING
    # --------------------------------------------------------

    render_waveform(
        wave_placeholder,
        "thinking"
    )

    status_placeholder.markdown(
        """
        <p style="
            text-align:center;
            color:#9a9a9a;
        ">
            Thinking...
        </p>
        """,
        unsafe_allow_html=True
    )


    # --------------------------------------------------------
    # AI
    # --------------------------------------------------------

    reply = get_reply(text)


    # --------------------------------------------------------
    # ASSISTANT MESSAGE
    # --------------------------------------------------------

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": reply
        }
    )


    with st.chat_message(
        "assistant",
        avatar="🎙️"
    ):

        st.write(reply)


    # --------------------------------------------------------
    # GENERATE VOICE
    # --------------------------------------------------------

    render_waveform(
        wave_placeholder,
        "speaking"
    )

    status_placeholder.markdown(
        """
        <p style="
            text-align:center;
            color:#9a9a9a;
        ">
            Speaking...
        </p>
        """,
        unsafe_allow_html=True
    )


    try:

        mp3_bytes = speak(reply)

        st.session_state.last_audio = mp3_bytes

        play_audio(mp3_bytes)

    except Exception as e:

        st.warning(
            f"Voice generation failed: {e}"
        )

        mp3_bytes = None


    # --------------------------------------------------------
    # IMPORTANT:
    # DON'T IMMEDIATELY RERUN.
    #
    # The old version did:
    #
    # play_audio(...)
    # time.sleep(0.2)
    # st.rerun()
    #
    # That could destroy the audio iframe.
    # --------------------------------------------------------

    if st.session_state.listening:

        # Give the browser a moment to begin playback.

        time.sleep(1.5)

        status_placeholder.markdown(
            """
            <p style="
                text-align:center;
                color:#ff8ea0;
            ">
                Listening...
            </p>
            """,
            unsafe_allow_html=True
        )


# ============================================================
# CONTINUOUS VOICE MODE
# ============================================================

if st.session_state.listening:

    status_placeholder.markdown(
        """
        <p style="
            text-align:center;
            color:#ff8ea0;
        ">
            Listening...
        </p>
        """,
        unsafe_allow_html=True
    )


    heard = st_javascript(
        _LISTEN_JS
    )


    if heard == "__UNSUPPORTED__":

        st.error(
            "Your browser does not support "
            "live speech recognition. "
            "Try Google Chrome or Microsoft Edge."
        )

        st.session_state.listening = False


    elif heard:

        handle_new_message(
            heard
        )

        # Restart listening after MOMO's response.

        if st.session_state.listening:

            time.sleep(0.5)

            st.rerun()


# ============================================================
# TYPED CHAT
# ============================================================

typed = st.chat_input(
    "...or type here"
)


if typed:

    handle_new_message(
        typed
    )
```
