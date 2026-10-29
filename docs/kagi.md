# kagi 経由で AI を使う（キーをヤタに置かない）

ふつうは `.env` に API キーを書きます。この方法では、ヤタが乗っ取られたとき（たとえば、読ませた Web ページにプロンプトインジェクションが仕込まれていたとき）に、キーそのものが盗まれるおそれがあります。

[kagi](https://github.com/koheip/kagi) を間に置くと、ヤタは本物のキーを持ちません。

- ヤタが持つのは、**mTLS のクライアント証明書**と、**数分で切れるトークン**だけです。
- 本物のキーは kagi が上流の API に送る直前に付けます。上流がキーを返してきても、kagi が伏字にします。
- kagi のポリシーで許した API（たとえば `POST /v1/chat/completions` だけ）しか呼べません。トークンごとの回数の上限もかけられます。
- トークンは証明書に結びついているので、トークンだけ盗まれても、ほかの PC からは使えません。
- 通信は TLS 1.3 で、耐量子のハイブリッド鍵交換（X25519MLKEM768）を使えます。

## 設定

1. kagi の README に沿って、kagi を起動し、エージェント `yata` の証明書を発行します。

   ```bash
   kagi-ca issue -dir pki -kind agent -name yata
   ```

2. kagi のポリシーに、`yata` が使ってよい上流と API を書きます（例は kagi の `examples/policy.example.json`）。

3. ヤタの `.env` に次を書きます。

   ```dotenv
   KAGI_URL=https://localhost:8443
   KAGI_CA_FILE=C:/kagi/pki/ca.crt
   KAGI_CERT_FILE=C:/kagi/pki/yata.crt
   KAGI_KEY_FILE=C:/kagi/pki/yata.key
   KAGI_UPSTREAM=openai
   KAGI_MODEL=gpt-4o-mini
   ```

4. ヤタを起動し、モデルの選択で「kagi 経由（キーをヤタに置かない）」を選びます。

## 動き

- 最初の質問のときに、kagi からトークンをもらいます（`KAGI_TOKEN_TTL` の長さ。ポリシーの上限より長くはなりません）。
- トークンの期限の30秒前、または kagi が「取り直して」と返したとき（期限切れ・回数の上限。`X-Kagi-Token: renew`）に、自動でもらい直します。
- 上流の API 自身の 429（混雑）では、もらい直しません。
- kagi が拒否したときは「kagi のポリシーと証明書の期限を確認してください」と表示します。

## 注意

- kagi を `-pq-only`（耐量子の鍵交換だけを許可）で動かす場合、ヤタの Python が OpenSSL 3.5 以降を使っている必要があります。
- 証明書の秘密鍵（`yata.key`）は、API キーと同じように大切に扱ってください。`.env` と同じく、Git に入れないでください。
