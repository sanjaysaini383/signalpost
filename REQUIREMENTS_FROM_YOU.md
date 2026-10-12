# What I need from you

Things I cannot do from my side (accounts, keys, emails, decisions). Ordered by importance.
**Hard deadline: 17 Oct 2026, 11:59 PM IST.** Code revisions are allowed until 18 Oct.

## 1. Before you submit (blocking)

- [ ] **Register on Unstop** for "Signalpost: Build An Agent That Finds Company Information" and share the project
  link: https://github.com/sanjaysaini383/signalpost
- [ ] **Read the Builderr/Unstop rules page** and tell me if it specifies:
  - the exact format of the "company profiles" (JSON per company? one JSONL? a specific schema?),
  - how "one command to run" will be invoked (working directory, Python version, input format for the 100 daily org numbers),
  - what "declared external API costs" must look like.
  My output is `output/profiles/<orgno>.json`, `output/profiles.jsonl` and `output/summary.csv`. That is a guess until you confirm.
- [ ] **Hand-check about 50 profiles** against https://virksomhet.brreg.no/ (replace the org number in the URL, or open
  the dashboard with `py -m signalpost report` and use each fact's source link). A wrong-company publication or a
  fabricated financial value disqualifies the entry, so this is worth the time. I can only check structure
  automatically (`py -m signalpost validate`), not truth against the real world.
- [ ] **Final submission email** to `submit@builderr.ai` containing:
  1. repository link: https://github.com/sanjaysaini383/signalpost
  2. the exact commit hash (`git rev-parse HEAD`, after the last commit and push)
  3. the run command: `py -m signalpost run --input companies.txt`
  4. model/API details and expected cost (copy from README.md "Limits and expected cost")
  5. the 1,000+ profiles (already in `output/` in the repo)

## 2. Needed for the best score

- [ ] **Anthropic API key** (https://console.anthropic.com). Put it in a local `.env` or the `ANTHROPIC_API_KEY`
  environment variable. Without it the optional website-summary step is skipped and everything else still works.
  That step is unit-tested with a fake client (quote must appear verbatim on the page, numbers must be inside the quote),
  but **has never run against the live API**. After you add a key, run
  `py -m signalpost profile 923609016` and check that `business_summary` / `product_or_service` facts appear and
  that their quotes really are on the company's site.
- [ ] **Tell me what JBOX is.** The prize page mentions a separate $500 bonus for "agents built with JBOX" and says
  nothing else. If you find docs or a link, send them and I will check whether adopting it is cheap.
- [ ] **Decide on profile size in the repo.** `output/` is about 40 MB (each profile as its own file, plus the same
  data in `profiles.jsonl`). If that is too heavy for the submission, tell me which one to keep.

## 3. Optional, your call

- [ ] **Push approval.** I commit locally and do not push unless you say so. Tell me when to push.
- [ ] **Doffin / Kunngjoringer data.** The announcements site has no structured open API that I could find. If you
  know a working endpoint, or want procurement data added, tell me.
- [ ] **Refresh just before sending.** Run `py -m signalpost run --input companies.txt` again on the day you email,
  so the profiles are current. It takes about 8 minutes and records any real changes.

## 4. Things to watch

- Do not paste your API key into chat, commits or the repo. `.env` is git-ignored.
- Daily test limits are 45 min / 2,000 requests / $10. A 100-company run takes about 700 requests and about one minute
  (measured), so there is a lot of headroom.
- LLM prices in the README were checked on 11 Oct 2026 (Haiku 5.5: $0.10 in / $0.50 out per million tokens).
  Re-check before you send the cost estimate.
- I cannot measure the coverage score (35 points) because the checked reference collection is private. The agent
  collects as many verifiable facts as it can, but whether that clears the 21/35 coverage bar is unknown until
  Builderr scores it.
