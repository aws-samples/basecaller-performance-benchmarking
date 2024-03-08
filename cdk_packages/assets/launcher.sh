#!/bin/bash
# log UserData script output, source: https://alestic.com/2010/12/ec2-user-data-output/
exec > >(tee -a /var/log/launcher.log | logger -t launcher -s 2>/dev/console) 2>&1
echo -----
echo ----- start script
echo -----

echo ----- update system -----

apt-get update
apt-get upgrade -y
apt-get install unzip -y
apt-get install jq -y

echo ----- install AWS CLI -----

curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip -qq awscliv2.zip
./aws/install

echo ----- get token to access instance metadata -----

TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/dynamic/instance-identity/document | jq --raw-output .region)

echo ----- install download script -----

script_file=$(eval '/usr/local/bin/aws ssm get-parameters --region '"$region"' --names /ONT-performance-benchmark/download-script --query '"'"'Parameters[0].Value'"'"' --output text')
aws s3 cp "$script_file" /download_files.sh
chmod +x /download_files.sh
echo "@reboot /download_files.sh" >> /var/spool/cron/crontabs/root
sudo chmod 600 /var/spool/cron/crontabs/root

echo -----
echo ----- end script -----
echo -----

# Trigger reboot. Download script will run after reboot.
shutdown -r now
