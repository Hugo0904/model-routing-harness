# Model Routing Harness

MRH-001 的獨立專案；目前交付 **E1 能力盤點**。尚未實作分級核心、Jev 網路接頭、產品 CLI、安裝器或正式 Hook，不能視為可用路由器。

完整使用者基準在 [REQUIREMENTS.md](REQUIREMENTS.md)，唯一執行／驗收記錄在 [docs/MRH-001.md](docs/MRH-001.md)。盤點結果與下一段建議在 [docs/capabilities.md](docs/capabilities.md)。

可重現的 E1 probe：

```sh
python3 scripts/probe_codex_contracts.py \
  --binary /Users/shawn/.nvm/versions/node/v20.19.4/bin/codex \
  --binary /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
  --output /private/tmp/mrh-e1-contracts.json
```

這是本機命令示例，移機時使用該機已確認的 CLI 路徑。Probe 只在暫存目錄取得安裝版本的 schema、讀取合成設定、列出未信任 Hook，不啟動模型、不讀真實憑證、不啟用正式 Hook。結果只證明這些契約邊界。
