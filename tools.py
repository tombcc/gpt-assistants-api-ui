import json
from PIL import Image
import pytesseract
from openai import OpenAI
import cv2
from pathlib import Path
from pydub import AudioSegment
from gtts import gTTS

# Load the configuration
def load_config():
    with open('chat_config.json', 'r') as f:
        config = json.load(f)
    return config

config = load_config()

# Initialize OpenAI client with API key from config
client = OpenAI(api_key=config.get("OPENAI_API_KEY"))

def image_to_text(image_path):
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        return f"Error recognizing text from image: {str(e)}"

def process_image_with_openai(image_path):
    try:
        text = image_to_text(image_path)
        response = client.completions.create(
            engine="text-davinci-003",
            prompt=f"The following text was recognized from an image: '{text}'. Please provide a detailed explanation or description based on this text.",
            max_tokens=150
        )
        return response.choices[0].text.strip()
    except Exception as e:
        return f"Error processing image with OpenAI: {str(e)}"

def extract_frames_from_video(video_path, frame_rate_ratio=1, max_frames=100):
    frames = []
    try:
        vidcap = cv2.VideoCapture(video_path)
        frame_rate = int(vidcap.get(cv2.CAP_PROP_FPS))
        interval = max(1, frame_rate // frame_rate_ratio)
        success, image = vidcap.read()
        count = 0
        while success and len(frames) < max_frames:
            if count % interval == 0:
                frame_path = f"/tmp/frame_{count}.jpg"
                cv2.imwrite(frame_path, image)
                frames.append(frame_path)
            success, image = vidcap.read()
            count += 1
        vidcap.release()
    except Exception as e:
        return f"Error extracting frames from video: {str(e)}"
    return frames

def summarize_video_motion(video_path, frame_rate_ratio=1, max_frames=100):
    frames = extract_frames_from_video(video_path, frame_rate_ratio, max_frames)
    summaries = []
    for frame in frames:
        summary = process_image_with_openai(frame)
        summaries.append(summary)
    return " ".join(summaries)

def text_to_speech_streaming(text, output_path="speech.mp3"):
    try:
        tts = gTTS(text)
        tts.save(output_path)
        return output_path
    except Exception as e:
        return f"Error converting text to speech: {str(e)}"

def transcribe_audio(file_path):
    try:
        with open(file_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return transcription.text
    except Exception as e:
        return f"Error transcribing audio: {str(e)}"

TOOL_MAP = {
    "image_to_text": image_to_text,
    "process_image_with_openai": process_image_with_openai,
    "summarize_video_motion": summarize_video_motion,
    "text_to_speech_streaming": text_to_speech_streaming,
    "transcribe_audio": transcribe_audio
}