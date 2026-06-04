#!/bin/bash
# 在连接新 VPN 之前运行此脚本
# 作用：固定 idealab.alibaba-inc.com 的路由走公司网关
# 这样新 VPN 接管默认路由后，Claude API 仍然可用

set -e

DOMAIN="idealab.alibaba-inc.com"

# 获取当前默认网关和接口
DEFAULT_GW=$(netstat -rn -f inet | grep '^default' | head -1 | awk '{print $2}')
DEFAULT_IF=$(netstat -rn -f inet | grep '^default' | head -1 | awk '{print $NF}')

if [ -z "$DEFAULT_GW" ]; then
    echo "❌ 无法获取默认网关，请检查网络连接"
    exit 1
fi

echo "当前默认网关: $DEFAULT_GW (接口: $DEFAULT_IF)"

# 解析域名 IP
IDEALAB_IP=$(dig +short "$DOMAIN" | grep -E '^[0-9]+\.' | head -1)

if [ -z "$IDEALAB_IP" ]; then
    echo "❌ 无法解析 $DOMAIN，请确认 DNS 正常"
    exit 1
fi

echo "解析到 $DOMAIN -> $IDEALAB_IP"

# 添加主机路由（需要 sudo）
echo "正在添加路由: $IDEALAB_IP -> $DEFAULT_GW ..."
sudo route add -host "$IDEALAB_IP" "$DEFAULT_GW"

echo "✅ 路由已固定！现在可以安全连接新 VPN 了"
echo ""
echo "连接新 VPN 后，可以验证："
echo "  curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN"
echo ""
echo "用完后清理路由："
echo "  sudo route delete -host $IDEALAB_IP"
