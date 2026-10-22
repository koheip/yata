# ヤタ（Yata）を Windows で使えるように準備するスクリプト。
#
# 使い方（リポジトリの中で）:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# リポジトリを公開したあとは、次の1行でも動きます（~\yata に取得します。YATA_DIR で変更できます）:
#   irm https://raw.githubusercontent.com/koheip/yata/main/scripts/install.ps1 | iex
#
# このスクリプトは uv / Node.js / Git を勝手にインストールしません。
# 見つからないときは、入れ方を表示して止まります。
# 行うのは、依存パッケージの取得（uv sync / npm ci）、画面のビルド、.env の作成（なければ）だけです。

function Install-Yata {
    $ErrorActionPreference = 'Stop'

    function Show-Missing([string]$name, [string[]]$lines) {
        Write-Host ""
        Write-Host "$name が見つかりません。次のどれかの方法で入れてから、もう一度実行してください。" -ForegroundColor Yellow
        foreach ($line in $lines) { Write-Host "  $line" }
        Write-Host ""
    }

    function Invoke-Step([string]$label, [scriptblock]$block) {
        Write-Host "==> $label" -ForegroundColor Cyan
        & $block
        if ($LASTEXITCODE -ne 0) {
            throw "「$label」に失敗しました（終了コード $LASTEXITCODE）。上のメッセージを確認してください。"
        }
    }

    # uv を標準の場所に入れている場合は、このセッションだけ PATH に足す。
    $uvHome = Join-Path $HOME '.local\bin'
    if ((Test-Path (Join-Path $uvHome 'uv.exe')) -and -not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $env:Path = "$uvHome;$env:Path"
    }

    # リポジトリの場所を決める。スクリプトとして実行されたらその親、irm | iex なら取得する。
    $root = $null
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot '..\pyproject.toml'))) {
        $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    } else {
        $target = if ($env:YATA_DIR) { $env:YATA_DIR } else { Join-Path $HOME 'yata' }
        if (Test-Path (Join-Path $target 'pyproject.toml')) {
            $root = (Resolve-Path $target).Path
        } elseif (Test-Path $target) {
            Write-Host "$target はすでにあり、ヤタのフォルダではありません。YATA_DIR で別の場所を指定してください。" -ForegroundColor Yellow
            return
        } else {
            if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
                Show-Missing 'Git' @('winget install --id Git.Git -e', 'https://git-scm.com/download/win')
                return
            }
            Invoke-Step 'ヤタを取得' { git clone https://github.com/koheip/yata.git $target }
            $root = (Resolve-Path $target).Path
        }
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Show-Missing 'uv' @(
            'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
            'winget install --id astral-sh.uv -e',
            '詳しくは https://docs.astral.sh/uv/getting-started/installation/'
        )
        return
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Show-Missing 'Node.js（npm）' @('winget install --id OpenJS.NodeJS.LTS -e', 'https://nodejs.org/ja/download')
        return
    }

    Push-Location $root
    try {
        Invoke-Step 'Python の依存関係をそろえる（uv sync）' { uv sync --all-groups }
        if (Test-Path 'frontend\package-lock.json') {
            Invoke-Step '画面の依存関係をそろえる（npm ci）' { npm --prefix frontend ci }
        } else {
            Invoke-Step '画面の依存関係をそろえる（npm install）' { npm --prefix frontend install }
        }
        Invoke-Step '画面をビルド' { npm --prefix frontend run build }

        if (-not (Test-Path '.env')) {
            Copy-Item '.env.example' '.env'
            Write-Host '.env を作りました。API キー（GEMINI_API_KEY など）を1つ書いてください。' -ForegroundColor Green
        } else {
            Write-Host '.env はすでにあるので、そのままにしました。'
        }

        Write-Host ""
        Write-Host '準備ができました。' -ForegroundColor Green
        Write-Host "  起動:  cd `"$root`"; uv run yata"
        Write-Host '  画面:  http://127.0.0.1:8741'
        Write-Host '  ブラウザ操作を使うときは、追加で: uv run playwright install chromium'
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

Install-Yata
