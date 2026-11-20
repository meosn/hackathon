"""Run the acceptance walk-through against the API, with no third-party dependencies."""

import argparse
import io
import json
import time
import uuid
import wave
from urllib import error, request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument(
        "--third-profile",
        action="store_true",
        help="Register a temporary custom listener",
    )
    args = p.parse_args()

    def call(path, token=None, body=None, method=None):
        req = request.Request(
            args.api + path,
            method=method or ("POST" if body is not None else "GET"),
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": "Bearer " + token} if token else {}),
            },
        )
        with request.urlopen(req, timeout=35) as res:
            payload = res.read()
            return (
                json.loads(payload)
                if "json" in res.headers.get("Content-Type", "")
                else payload
            )

    print("Ready:", call("/ready"))
    leaders = []
    tokens = {}
    for profile in ("tech", "finance"):
        token = tokens[profile] = call("/auth/demo", body={"profile": profile})[
            "access_token"
        ]
        accepted = call("/briefings", token, {"period": "week"})
        path = "/briefings/" + accepted["briefing_id"]
        deadline = time.monotonic() + args.timeout
        while True:
            item = call(path, token)
            if item["status"] == "completed":
                break
            if item["status"] == "failed" or time.monotonic() > deadline:
                raise RuntimeError(
                    f"Briefing stopped at {item['status']}: {item['error']}"
                )
            time.sleep(0.5)
        leaders.append(item["items"][0]["title"])
        segments = call(path + "/transcript", token)
        factual = [s for s in segments if s["claim_ids"]]
        assert factual and all(
            s["citations"] and s["source_article_ids"] for s in factual
        )
        with wave.open(io.BytesIO(call(path + "/audio", token)), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
            assert seconds > 0 and abs(seconds - segments[-1]["end_seconds"]) < 0.05
        story = call("/stories/" + item["items"][0]["story_id"], token)
        for fact in story["facts"]:
            for evidence in fact["evidence"]:
                assert evidence["end"] > evidence["start"] and evidence["excerpt"]
        conv = call("/conversations", token, {"briefing_id": item["id"]})
        answer = call(
            "/conversations/" + conv["id"] + "/messages",
            token,
            {"text": "What do other sources say?"},
        )
        assert answer["citations"]
        print(
            profile,
            item["language"],
            leaders[-1],
            f"{seconds:.2f}s",
            f"{len(factual)} cited statements",
        )
        print(
            "  Source:",
            answer["citations"][0]["source"],
            "—",
            answer["citations"][0]["excerpt"],
        )
    assert leaders[0] != leaders[1], "Demo profiles should lead with different stories"
    if args.third_profile:
        import secrets

        uid = uuid.uuid4().hex
        token = call(
            "/auth/register",
            body={
                "email": f"listener-{uid}@example.org",
                "name": "Climate listener",
                "password": secrets.token_urlsafe(24),
            },
        )["access_token"]
        call(
            "/users/me/preferences",
            token,
            {"interests": ["energy", "climate"], "duration_minutes": 2},
            method="PATCH",
        )
        custom = call("/recommendations?period=week", token)
        assert custom
        print("Custom listener leads with:", custom[0]["title"])
    print(
        json.dumps(call("/metrics/costs", tokens["tech"]), indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
