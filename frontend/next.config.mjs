/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config) => {
    // Konva intenta cargar el módulo nativo `canvas` cuando lo analiza Node.
    // En el navegador no se usa, así que lo marcamos como external para que
    // webpack no intente resolverlo en el bundle del servidor.
    config.externals = [...(config.externals || []), { canvas: "commonjs canvas" }];
    return config;
  },
};

export default nextConfig;
