$port = 8742
$envPath = Join-Path $PSScriptRoot '..\.env'
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*LINE_WEBHOOK_PORT\s*=\s*["'']?(\d+)["'']?\s*(?:#.*)?$') {
            $parsedPort = 0
            if ([int]::TryParse($Matches[1], [ref]$parsedPort) -and $parsedPort -ge 1 -and $parsedPort -le 65535) {
                $port = $parsedPort
            }
        }
    }
}

if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    Write-Host '表示された https://….trycloudflare.com に /line/webhook を付けて LINE Developers の Webhook URL に設定してください'
    & cloudflared tunnel --url "http://127.0.0.1:$port"
} else {
    Write-Host 'cloudflared が見つかりません。必要なら次のコマンドでインストールしてください（このスクリプトはインストールしません）。'
    Write-Host 'winget install --id Cloudflare.cloudflared'
    Write-Host 'または ngrok を利用できます（既定ポート 8742 の例。変更した場合は読み替えてください）。'
    Write-Host 'ngrok http 8742'
    Write-Host '無料の固定ドメインを使う場合:'
    Write-Host 'ngrok http --url=<your>.ngrok-free.app 8742'
}
