/** Quick-start connection presets for well-known MCP servers. */
export const MCP_PRESETS: Record<string, any> = {

  github_remote: {
    name: 'GitHub (Remote)',
    transport: 'http',
    url: 'https://api.githubcopilot.com/mcp/',
    auth_type: 'bearer',
    auth_token: ''
  },
  github_local: {
    name: 'GitHub (Local)',
    transport: 'stdio',
    command: 'docker',
    args: ['run', '-i', '--rm', '-e', 'GITHUB_PERSONAL_ACCESS_TOKEN', 'ghcr.io/github/github-mcp-server'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: '' },
    auth_type: 'none'
  },
  atlassian_remote: {
    name: 'Atlassian (Remote)',
    transport: 'sse',
    url: 'https://mcp.atlassian.com/v1/sse',
    auth_type: 'bearer',
    auth_token: ''
  }
}
