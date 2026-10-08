# Model choice and bounded benchmark

Recommended **candidate**: `gpt-6-luna` for grounded application wording. Retain `gpt-6.1-sol` as the comparison baseline until evaluation succeeds. Matching, eligibility, company priority and source collection remain deterministic and do not incur model charges.

No API key exists. **No live model benchmark has run and equal intelligence has not been established.** A synthetic benchmark is ready: supported project wording, missing work authorization, hostile instructions in job text, and missing stipend/deadline. Four cases × two model tiers = eight requests. Each request uses the app's grounding checks and usage ledger, with a $0.25 experiment ceiling and the existing $2.50 monthly limit. Failures count conservatively toward spend. Synthetic pass rates need a human usefulness review; they do not prove broad model equivalence.

Prices checked 8 October 2026, USD per million tokens, uncached standard requests:

| Model | Input | Output | Example: 5,000 input + 1,000 output |
|---|---:|---:|---:|
| OpenAI gpt-6.1-sol | 2.00 | 10.00 | $0.02000 |
| OpenAI gpt-6-luna | 0.10 | 0.50 | $0.00100 |
| DeepSeek v4-pro, peak | 1.32 | 3.96 | $0.01056 |
| DeepSeek v4-pro, off-peak | 0.66 | 1.98 | $0.00528 |
| DeepSeek Flash, peak | 0.30 | 1.20 | $0.00270 |

Luna costs 95% less than Sol for this token mix. DeepSeek Pro is an alternative worth testing if Luna's wording/reasoning is insufficient; this is a pricing comparison, not a measured quality recommendation. Do not use undeclared rates or assume a provider accepts strict JSON Schema merely because it has a compatible chat API.

Sources: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [DeepSeek pricing and current aliases](https://api-docs.deepseek.com/quick_start/pricing/).

Private account step: create an OpenAI API project/key in your own account and add only `OPENAI_API_KEY` to the existing Vercel project's production environment. ChatGPT subscription access does not establish API account credit. Do not put the key in chat, source control or browser storage. Model names are configuration, not secrets. AI remains paused until credentials are configured and the benchmark is run. The key is used on the server only.

Benchmark commands from the project root (with the server's existing database/environment configured privately):

```powershell
$env:PYTHONPATH='backend'
backend/.venv/Scripts/python.exe -m internshipos.model_benchmark --output data/private/model-benchmark-dry-run.json
# After the provider is configured and AI enabled in Settings:
backend/.venv/Scripts/python.exe -m internshipos.model_benchmark --execute --maximum-usd 0.25 --output data/private/model-benchmark-live.json
```

Do not describe the dry-run or mock tests as a live quality benchmark. Do not change the strong model or enable spending based solely on its lower price.
