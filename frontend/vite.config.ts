import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default ({ mode }) => {
  Object.assign(process?.env, loadEnv(mode, process?.cwd(), ""));

  const SERVER_URL = process?.env?.SERVER_URL || "http://localhost:5000";

  return defineConfig({
    server: {
      proxy: {
        "/api": {
          target: SERVER_URL,
          changeOrigin: true,
        },
        "/ws": {
          target: SERVER_URL,
          changeOrigin: true,
          ws: true,
        },
        "/addons": {
          target: SERVER_URL,
          changeOrigin: false,
        },
        "/graphql": {
          target: SERVER_URL,
          changeOrigin: true,
        },
      },
    },
    plugins: [react()],
    base: "",
  });
};
