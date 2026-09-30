import {
  createModuleFederationConfig,
  pluginModuleFederation,
} from "@module-federation/rsbuild-plugin";
import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

import ConcatenatePlugin from "./ConcatenatePlugin";

const mfConfig = createModuleFederationConfig({
  name: "BomDashboardWidget",
  remotes: {
    doover_admin: "doover_admin@[window.dooverAdminSite_remoteUrl]",
    customer_site: "customer_site@[window.dooverCustomerSite_remoteUrl]",
  },
  exposes: {
    "./BomDashboardWidget": "./src/BomDashboardWidget",
  },
  shared: {
    react: { singleton: true, requiredVersion: "^18.3.1", eager: true },
    "react-dom": { singleton: true, requiredVersion: "^18.3.1", eager: true },
    "react-router": { singleton: true, requiredVersion: false, eager: true },
    "doover-js": { singleton: true, requiredVersion: false, eager: true },
    "doover-js/react": {
      singleton: true,
      requiredVersion: false,
      eager: true,
    },
    "@tanstack/react-query": {
      singleton: true,
      requiredVersion: false,
      eager: true,
    },
  },
});

export default defineConfig({
  tools: {
    rspack: {
      plugins: [
        new ConcatenatePlugin({
          source: "./dist",
          destination: "./assets",
          name: "BomDashboardWidget.js",
          ignore: ["main.js"],
        }),
      ],
    },
  },
  output: {
    injectStyles: true,
  },
  performance: {
    chunkSplit: {
      strategy: "all-in-one",
    },
  },
  plugins: [pluginReact(), pluginModuleFederation(mfConfig)],
});
