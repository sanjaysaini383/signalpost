# What I need from you

Things I cannot do from my side (accounts, keys, emails, decisions). Ordered by deadline.
**Hard deadline: 17 Oct 2026, 11:59 PM IST.** Code revisions allowed until 18 Oct.

## 1. Before you submit (blocking)

- [ ] **Register on Unstop** for "Signalpost: Build An Agent That Finds Company Information" and keep the project link.
- [ ] **Read the Builderr/Unstop rules page** and tell me if it specifies:
  - the exact format of the "company profiles" file (JSON per company? one JSONL? a specific schema?),
  - how "one command to run" will be invoked (working directory, Python version, input format for the 100 daily org numbers),
  - what "declared external API costs" must look like.
  My output (`output/profiles/<orgno>.json`) is a guess until you confirm this.
- [ ] **Check the eligibility and team rules** (individual participation) apply to you.
- [ ] **Final submission email** to `submit@builderr.ai` from you containing:
  1. repository link: https://github.com/sanjaysaini383/signalpost
  2. the exact commit hash (I will give it to you after the last commit; run `git rev-parse HEAD`)
  3. the run command: `py -m signalpost run --input companies.txt`
  4. model/API details and expected cost (copy from README.md "Limits and expected cost")
  5. the 1,000+ profiles (already in `output/profiles/` in the repo)

## 2. Needed for the best score

- [ ] **Anthropic API key** (https://console.anthropic.com). Put it in a local `.env` or as `ANTHROPIC_API_KEY`.
  Without it the website-summary step is skipped. That step is written and unit-tested for the "drop anything not
  quoted from the page" rule, but **I have not been able to run it against the live API**. Once you have a key,
  run `py -m signalpost profile <an org number that has a website>` and check the output.
- [ ] **Decide whether to commit the profiles** (about 15 MB) or attach them to the email. I've assumed commit.
- [ ] **Tell me what JBOX is.** The prize page mentions a separate $500 bonus for "agents built with JBOX" and says
  nothing else. If you find its docs/link, send them; I'll check whether adopting it is cheap.

## 3. Optional, your call

- [ ] **Push access / push approval:** I committed locally only. Tell me when to push again.
- [ ] **Doffin / Kunngjøringer data:** I tried the Brønnøysund announcements endpoint and found no stable open API,
  so it is not included. If you know a working endpoint or want Doffin procurement data added, tell me.
- [ ] **Accounts for a hand audit:** I can run automated checks (`py -m signalpost validate`), but a human should
  spot-check ~50 profiles against brreg.no for wrong-company or wrong-value errors. A wrong-company publication
  disqualifies the entry, so this is worth 30 minutes of your time.

## 4. Things to watch

- Do not paste your API key into chat, commits or the repo. `.env` is git-ignored.
- Daily test limits are 45 min / 2,000 requests / $10. Default settings stay well under that
  (about 400-600 requests for 100 companies).
- LLM prices in the README were checked on 11 Oct 2026 (Haiku 5.5: $0.10 in / $0.50 out per million tokens).
  Re-check before you send the cost estimate.
