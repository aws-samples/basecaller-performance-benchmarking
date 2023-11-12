#!/bin/bash
exec > >(tee /var/log/mount-fsx.log | logger -t mount-fsx -s 2>/dev/console) 2>&1

# mount the FSx for Lustre file system
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/dynamic/instance-identity/document | jq --raw-output .region)
fsx_dns_mount_name=$(eval '/usr/local/bin/aws ssm get-parameters --region '$region' --names /ONT-performance-benchmark/fsx-lustre-dns-mount-name --query '"'"'Parameters[0].Value'"'"' --output text')
mkdir -p /fsx
mount -t lustre -o noatime,flock "${fsx_dns_mount_name}" /fsx
