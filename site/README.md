# ヤタの紹介・ダウンロードサイト

GitHub Pages で公開する静的サイトです（ビルド不要）。`.github/workflows/pages.yml` が、`main` に push するたびに公開します。

## はじめて公開するとき

1. GitHub のリポジトリの Settings → Pages で、Source を「GitHub Actions」にする。
2. 独自ドメインを使うなら、Settings → Pages の Custom domain に入れ、DNS を設定する（AdSense の審査は独自ドメインのほうが通りやすい）。
3. `index.html` の Microsoft Store のボタン（`<!-- STORE_URL -->` の行）を、Store の公開後にヤタのページの URL に変える。

## 広告（Google AdSense）

広告の枠は `<div class="ad" aria-label="広告"></div>` として各ページに置いてあります。中身が空のあいだは表示されません。

1. AdSense に申し込む（18 歳以上が必要。独自ドメインがおすすめ）。
2. 審査用のコードを、各ページの `<!-- AdSense: ... -->` の行に貼る。
3. 審査に通ったら、広告ユニットのコード（`<ins class="adsbygoogle" ...>`）を `.ad` の中に貼る。
4. AdSense の案内に従って、`ads.txt` をサイトの一番上（`site/ads.txt`）に置く。

注意：ダウンロードボタンのすぐ近くや、ボタンと見分けにくい場所に広告を置くと、AdSense の規約違反になります。今の枠はボタンから離してあります。

## 記事を足すとき

`articles/` に HTML を足し、`articles/index.html` とトップページの「使い方の記事」にリンクを足します。
