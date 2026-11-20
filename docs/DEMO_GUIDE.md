# The Liquid Briefing demonstration

Start the application using the root README. Wait for API readiness and open the listening room. A fresh deployment imports the bundled synthetic corpus. The first import establishes its reference date. All organizations, publications and events in the fixture are invented.

1. Choose **Technology enthusiast**. The signed-in dashboard recommends stories using the English technology profile. The hero generates an edition for the current listener.
2. Open **Explore stories**. Search for **Sunvale**, open the event and expand its facts. Compare the two synthetic reports giving the solar pilot's capacity as **40 megawatts** and **42 megawatts**. Both excerpts and publishers are visible. The system records the disagreement. Open the in-app record to read the stored source.
3. Open **Make a briefing** for a selected story, or return to **Generate briefing** on the dashboard to use the whole personalized ranking. Choose **week** and generate. The player becomes available once verification and speech finish. Press play, change speed, seek to another line, and expand a factual segment's evidence. The selected text follows the WAV sample timeline.
4. Use **Discuss this briefing** and ask “Explain the second story” or “What do other sources say?” Open the answer's evidence. A microphone upload requires the configured speech recognizer; text and spoken answers work with the default local providers.
5. Choose **Switch listener**, then **Financial analyst**. Generate another weekly edition with the default profile language. The finance edition leads with the Maren Bank rate decision in German. The English technology edition leads with Vela Labs' Aurora speech benchmark. Listening history and private briefings belong to each session.
6. Open **Transparency** as either demo listener. On a new synthetic import, 17 input records yield 16 retained articles, one exact duplicate, seven events, 28 supported assertions and two conflicting assertions. Repeat imports add to submitted and duplicate counts. The dashboard distinguishes measured usage, estimates and the fixed-listener 10× simulation.
7. Switch listener, register a new email and pick existing or custom interests, source exclusions, a language, duration and voice. Set a daily local time and time zone. Confirm the selection under **Settings**. The new account can generate a briefing immediately when evidence exists in its chosen language.

## Scripted run

From the project directory with the stack running:

```bash
python3 scripts/demo.py --third-profile
./scripts/verify-stack.sh
```

The first command creates two separate demo listeners, downloads and decodes each WAV, checks every factual segment for citations and article IDs, compares actual duration to the final transcript boundary, asks a follow-up and prints aggregate costs. The optional third profile registers a new temporary listener using a generated password. Each run creates new private editions. The second command also waits for durable news, synthesis and completion receipts.

For an alternative port pass `--api http://127.0.0.1:PORT/api/v1` to the Python script, or set `SOURCERA_API` for the shell verifier. Full browser tests live in `frontend/e2e`. See VALIDATION.md for the recorded run and precise scope.

For licensed material, follow DEPLOYMENT.md to load an operator-authorized export. The import keeps its original dates. For a past hackathon week, choose explicit stories from Explore; the selected-ID route can narrate older evidence. Before the licensing period ends, use the documented cleanup command.
