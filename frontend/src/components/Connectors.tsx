import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { Connector } from "../types"

type ConnectorsProps = {
  connectors: Connector[]
  onConnect: (connector: Connector) => void
  onDisconnect: (connector: Connector) => Promise<void>
}

function statusLabel(status: Connector["status"]): string {
  if (status === "connected") return "接続済み"
  if (status === "not_connected") return "未接続"
  return "未設定"
}

export function ConnectorsSection({ connectors, onConnect, onDisconnect }: ConnectorsProps) {
  if (connectors.length === 0) return null
  return (
    <div className="max-h-64 overflow-y-auto px-4 py-3">
      <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground">連携</p>
      <ul className="space-y-3">
        {connectors.map((connector) => (
          <li key={connector.id} className="text-sm">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{connector.label}</p>
              <Badge variant={connector.status === "connected" ? "secondary" : "outline"}>
                {statusLabel(connector.status)}
              </Badge>
            </div>
            {connector.status === "not_configured" ? (
              connector.setup_instructions ? (
                <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                  {connector.setup_instructions}
                </p>
              ) : null
            ) : connector.auth_kind === "token" && connector.status === "connected" ? (
              <p className="mt-1 text-xs text-muted-foreground">
                API トークンで接続中（.env で変更）
              </p>
            ) : (
              <div className="mt-1 flex gap-1">
                {connector.status === "connected" ? (
                  <Button type="button" size="xs" variant="outline" onClick={() => void onDisconnect(connector)}>
                    切断
                  </Button>
                ) : (
                  <Button type="button" size="xs" onClick={() => onConnect(connector)}>
                    接続
                  </Button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
