import path from 'path';
import { fileURLToPath } from 'url';
import webpack from 'webpack';
import { imageHosts } from './image-hosts.config.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));

function demoAccountsInBundle(dev) {
  const mode = process.env.NEXT_PUBLIC_IE_API_MODE;
  if (mode === 'mock') return true;
  if (mode === 'live') return false;
  return Boolean(dev);
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  productionBrowserSourceMaps: true,
  distDir: process.env.DIST_DIR || '.next',
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    remotePatterns: imageHosts,
    minimumCacheTTL: 60,
    qualities: [75, 85, 100],
  },
  webpack(
    config,
    {
      dev: dev
    }
  ) {
    if (!demoAccountsInBundle(dev)) {
      config.plugins.push(
        new webpack.NormalModuleReplacementPlugin(
          /[/\\]lib[/\\]mock[/\\]mockAuth\.ts$/,
          path.join(root, 'src/lib/mock/mockAuth.stub.ts')
        )
      );
    }
    if (dev) {
      config.module.rules.push({
        test: /\.(jsx|tsx)$/,
        exclude: [/node_modules/],
        use: [{
          loader: '@dhiwise/component-tagger/nextLoader',
        }],
      });
      const ignoredPaths = (process.env.WATCH_IGNORED_PATHS || '')
        .split(',')
        .map((p) => p.trim())
        .filter(Boolean);
      config.watchOptions = {
        ignored: ignoredPaths.length
          ? ignoredPaths.map((p) => `**/${p.replace(/^\/+|\/+$/g, '')}/**`)
          : undefined,
      };
    }
    return config;
  },
};
export default nextConfig;