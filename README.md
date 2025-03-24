# Assort Health Programming Assignment

<p>
  <a href="https://docs.livekit.io/agents/overview/">LiveKit Agents Docs</a>
  <a href="https://livekit.io/cloud">LiveKit Cloud</a>
</p>

This is an assignment created for an Assort Health interview. It is a basic example of a voice agent using LiveKit and Python.

Please hire me.

Best,
Fernando

## Dev Setup

Clone the repository and install dependencies to a virtual environment:

```console
# Linux/macOS
cd assort-health-assignment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python agent.py download-files
```

<details>
  <summary>Windows instructions (click to expand)</summary>

```cmd
:: Windows (CMD/PowerShell)
cd voice-pipeline-agent-python
python3 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
</details>


Set up the environment by copying `.env.example` to `.env.local` and filling in the required values:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `CARTESIA_API_KEY`
- `DEEPGRAM_API_KEY`
- `ELEVEN_API_KEY`
- `SENDGRID_API_KEY`

Run the agent:

```console
python agent.py dev
```

Run the tests:
```console
python scheduling_test.py
```

Heroku deployment:
```
git push heroku main
heroku ps:scale worker=1
heroku logs --tail
```

Set heroku configs:
```
heroku config:set SENDGRID_RECIPIENT_EMAILS="feruiloba@gmail.com,fruiloba@andrew.cmu.edu"
```