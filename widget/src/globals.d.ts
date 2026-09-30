declare module "customer_site/RemoteComponentWrapper" {
  import type { ReactNode } from "react";

  const RemoteComponentWrapper: (props: { children: ReactNode }) => JSX.Element;
  export default RemoteComponentWrapper;
}

declare module "customer_site/useRemoteParams" {
  export function useRemoteParams(): { agentId?: string | number } | null;
}
