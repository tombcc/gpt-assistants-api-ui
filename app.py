import os
import base64
import re
import json
import streamlit as st
from openai import OpenAI, AssistantEventHandler
from tools import TOOL_MAP
from typing_extensions import override
import streamlit.components.v1 as components

def load_config():
    with open('chat_config.json', 'r') as f:
        config = json.load(f)
    return config

def save_config(config):
    with open('chat_config.json', 'w') as f:
        json.dump(config, f, indent=4)

def str_to_bool(str_input):
    if not isinstance(str_input, str):
        return False
    return str_input.lower() == "true"

config = load_config()

# Load configuration variables
azure_openai_endpoint = config.get("AZURE_OPENAI_ENDPOINT")
azure_openai_key = config.get("AZURE_OPENAI_KEY")
openai_api_key = config.get("OPENAI_API_KEY")
authentication_required = str_to_bool(config.get("AUTHENTICATION_REQUIRED", False))
assistant_id = config.get("ASSISTANT_ID")
instructions = config.get("RUN_INSTRUCTIONS", "")
assistant_title = config.get("ASSISTANT_TITLE", "Assistants API UI")
enabled_file_upload_message = config.get("ENABLED_FILE_UPLOAD_MESSAGE", "Upload a file")

# Load authentication configuration
if authentication_required:
    if "credentials" in st.secrets:
        authenticator = stauth.Authenticate(
            st.secrets["credentials"].to_dict(),
            st.secrets["cookie"]["name"],
            st.secrets["cookie"]["key"],
            st.secrets["cookie"]["expiry_days"],
        )
    else:
        authenticator = None  # No authentication should be performed

client = None
if azure_openai_endpoint and azure_openai_key:
    client = OpenAI(
        api_key=azure_openai_key,
        api_version="2024-02-15-preview",
        azure_endpoint=azure_openai_endpoint,
    )
else:
    client = OpenAI(api_key=openai_api_key)

class EventHandler(AssistantEventHandler):
    @override
    def on_event(self, event):
        pass

    @override
    def on_text_created(self, text):
        st.session_state.current_message = ""
        with st.chat_message("Assistant"):
            st.session_state.current_markdown = st.empty()

    @override
    def on_text_delta(self, delta, snapshot):
        if snapshot.value:
            text_value = re.sub(
                r"\[(.*?)\]\s*\(\s*(.*?)\s*\)", "Download Link", snapshot.value
            )
            st.session_state.current_message = text_value
            st.session_state.current_markdown.markdown(
                st.session_state.current_message, True
            )

    @override
    def on_text_done(self, text):
        format_text = format_annotation(text)
        st.session_state.current_markdown.markdown(format_text, True)
        st.session_state.chat_log.append({"name": "assistant", "msg": format_text})

    @override
    def on_tool_call_created(self, tool_call):
        if tool_call.type == "code_interpreter" or tool_call.type == "image_recognition":
            st.session_state.current_tool_input = ""
            with st.chat_message("Assistant"):
                st.session_state.current_tool_input_markdown = st.empty()

    @override
    def on_tool_call_delta(self, delta, snapshot):
        if st.session_state.current_tool_input_markdown is None:
            with st.chat_message("Assistant"):
                st.session_state.current_tool_input_markdown = st.empty()

        if delta.type == "code_interpreter" or delta.type == "image_recognition":
            if delta.code_interpreter.input:
                st.session_state.current_tool_input += delta.code_interpreter.input
                input_code = f"### code interpreter\ninput:\n```python\n{st.session_state.current_tool_input}\n```"
                st.session_state.current_tool_input_markdown.markdown(input_code, True)

            if delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        pass

    @override
    def on_tool_call_done(self, tool_call):
        st.session_state.tool_calls.append(tool_call)
        if tool_call.type == "code_interpreter" or tool_call.type == "image_recognition":
            if tool_call.id in [x.id for x in st.session_state.tool_calls]:
                return
            input_code = f"### {tool_call.type}\ninput:\n```python\n{tool_call.code_interpreter.input}\n```"
            st.session_state.current_tool_input_markdown.markdown(input_code, True)
            st.session_state.chat_log.append({"name": "assistant", "msg": input_code})
            st.session_state.current_tool_input_markdown = None
            for output in tool_call.code_interpreter.outputs:
                if output.type == "logs":
                    output = f"### {tool_call.type}\noutput:\n```\n{output.logs}\n```"
                    with st.chat_message("Assistant"):
                        st.markdown(output, True)
                        st.session_state.chat_log.append(
                            {"name": "assistant", "msg": output}
                        )

def create_thread(content, file):
    messages = [
        {
            "role": "user",
            "content": content,
        }
    ]
    if file is not None:
        messages[0].update({"file_ids": [file.id]})
    thread = client.beta.threads.create()
    return thread

def create_message(thread, content, file):
    attachments = []
    if file is not None:
        attachments.append(
            {"file_id": file.id, "tools": [{"type": "code_interpreter"}]}
        )
    client.beta.threads.messages.create(
        thread_id=thread.id, role="user", content=content, attachments=attachments
    )

def create_file_link(file_name, file_id):
    content = client.files.content(file_id)
    content_type = content.response.headers["content-type"]
    b64 = base64.b64encode(content.text.encode(content.encoding)).decode()
    link_tag = f'<a href="data:{content_type};base64,{b64}" download="{file_name}">Download Link</a>'
    return link_tag

def format_annotation(text):
    citations = []
    text_value = text.value
    for index, annotation in enumerate(text.annotations):
        text_value = text.value.replace(annotation.text, f" [{index}]")

        if file_citation := getattr(annotation, "file_citation", None):
            cited_file = client.files.retrieve(file_citation.file_id)
            citations.append(
                f"[{index}] {file_citation.quote} from {cited_file.filename}"
            )
        elif file_path := getattr(annotation, "file_path", None):
            link_tag = create_file_link(
                annotation.text.split("/")[-1],
                file_path.file_id,
            )
            text_value = re.sub(r"\[(.*?)\]\s*\(\s*(.*?)\s*\)", link_tag, text_value)
    text_value += "\n\n" + "\n".join(citations)
    return text_value

def run_stream(user_input, file_info=None):
    file = file_info.get("file_data") if file_info else None
    uploaded_file = file_info.get("uploaded_file") if file_info else None
    file_type = file_info.get("type") if file_info else None
    
    if "thread" not in st.session_state:
        st.session_state.thread = create_thread(user_input, file)
    recognized_text = ""
    openai_response = ""
    audio_file_path = None

    # Check file type and process accordingly
    if uploaded_file and file_type.startswith("video"):
        file_path = f"/tmp/{uploaded_file.name}"
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        video_summary = TOOL_MAP["summarize_video_motion"](file_path)
        user_input += f"\n\nSummary of the video:\n{video_summary}"
    elif uploaded_file and file_type.startswith("image"):
        file_path = f"/tmp/{uploaded_file.name}"
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        recognized_text = TOOL_MAP["image_to_text"](file_path)
        openai_response = TOOL_MAP["process_image_with_openai"](file_path)
        user_input += f"\n\nRecognized text from image:\n{recognized_text}\n\nOpenAI's response based on the image:\n{openai_response}"
    elif uploaded_file and file_type.startswith("audio"):
        file_path = f"/tmp/{uploaded_file.name}"
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        transcription = TOOL_MAP["transcribe_audio"](file_path)
        user_input += f"\n\nTranscription of the audio:\n{transcription}"

    create_message(st.session_state.thread, user_input, file)

    with client.beta.threads.runs.stream(
        thread_id=st.session_state.thread.id,
        assistant_id=assistant_id,
        event_handler=EventHandler(),
    ) as stream:
        stream.until_done()

    if st.session_state.audio_response_enabled:
        # Generate speech for the assistant's response
        assistant_response = st.session_state.chat_log[-1]["msg"]  # Last message from the assistant
        audio_file_path = TOOL_MAP["text_to_speech_streaming"](assistant_response)
        st.session_state.audio_file_path = audio_file_path

        # Log the audio file path
        st.write(f"Audio file path: {audio_file_path}")

        # Check if the file exists
        if os.path.exists(audio_file_path):
            st.success("Audio file created successfully.")
        else:
            st.error("Audio file not found.")

def handle_uploaded_file(uploaded_file):
    file_data = client.files.create(file=uploaded_file, purpose="assistants")
    file_info = {
        "file_data": file_data,
        "uploaded_file": uploaded_file,  # store the uploaded_file
        "type": uploaded_file.type  # directly get the mimetype from uploaded_file
    }
    return file_info

def render_chat():
    for chat in st.session_state.chat_log:
        with st.chat_message(chat["name"]):
            st.markdown(chat["msg"], True)

if "tool_call" not in st.session_state:
    st.session_state.tool_calls = []

if "chat_log" not in st.session_state:
    st.session_state.chat_log = []

if "in_progress" not in st.session_state:
    st.session_state.in_progress = False

def disable_form():
    st.session_state.in_progress = True

def login():
    if st.session_state["authentication_status"] is False:
        st.error("Username/password is incorrect")
    elif st.session_state["authentication_status"] is None:
        st.warning("Please enter your username and password")
    if st.session_state["authentication_status"] is False:
        st.error("Username/password is incorrect")
    elif st.session_state["authentication_status"] is None:
        st.warning("Please enter your username and password")


def main():
    st.title(assistant_title)
    user_msg = st.chat_input(
        "Message", on_submit=disable_form, disabled=st.session_state.in_progress
    )

    if enabled_file_upload_message:
        uploaded_file = st.sidebar.file_uploader(
            enabled_file_upload_message,
            type=[
                "txt",
                "pdf",
                "png",
                "jpg",
                "jpeg",
                "csv",
                "json",
                "geojson",
                "mp4",
                "avi",
                "mov",
                "mp3",
                "wav",
                "m4a",
                "xlsx",
                "xls",
            ],
            disabled=st.session_state.in_progress
        )
    else:
        uploaded_file = None

    # Add toggle for audio response
    st.sidebar.header("Configuration")
    st.sidebar.checkbox("Enable Audio Response", key="audio_response_enabled", value=False)

    if user_msg:
        render_chat()
        with st.chat_message("user"):
            st.markdown(user_msg, True)
        st.session_state.chat_log.append({"name": "user", "msg": user_msg})

        file_info = None
        if uploaded_file is not None:
            file_info = handle_uploaded_file(uploaded_file)
        run_stream(user_msg, file_info)
        st.session_state.in_progress = False
        st.session_state.tool_call = None
        st.rerun()

    render_chat()

    if "audio_file_path" in st.session_state and st.session_state.audio_file_path:
        audio_file = st.session_state.audio_file_path
        st.write(f"Playing audio from: {audio_file}")  # Log the audio file path
        components.html(
        f"""
        <audio controls autoplay>
            <source src="file://{audio_file}" type="audio/mpeg">
            Your browser does not support the audio element.
        </audio>
        """,
        height=60,
    )

    config["AZURE_OPENAI_ENDPOINT"] = st.sidebar.text_input("Azure OpenAI Endpoint", config["AZURE_OPENAI_ENDPOINT"])
    config["AZURE_OPENAI_KEY"] = st.sidebar.text_input("Azure OpenAI Key", config["AZURE_OPENAI_KEY"])
    config["OPENAI_API_KEY"] = st.sidebar.text_input("OpenAI API Key", config["OPENAI_API_KEY"])
    config["AUTHENTICATION_REQUIRED"] = st.sidebar.checkbox("Authentication Required", config["AUTHENTICATION_REQUIRED"])
    config["ASSISTANT_ID"] = st.sidebar.text_input("Assistant ID", config["ASSISTANT_ID"])
    config["RUN_INSTRUCTIONS"] = st.sidebar.text_area("Run Instructions", config["RUN_INSTRUCTIONS"])
    config["ASSISTANT_TITLE"] = st.sidebar.text_input("Assistant Title", config["ASSISTANT_TITLE"])
    config["ENABLED_FILE_UPLOAD_MESSAGE"] = st.sidebar.text_input("Enabled File Upload Message", config["ENABLED_FILE_UPLOAD_MESSAGE"])

    if st.sidebar.button("Save Configuration"):
        save_config(config)
        st.sidebar.success("Configuration saved!")

if __name__ == "__main__":
    main()