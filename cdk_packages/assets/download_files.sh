#!/bin/bash
# log UserData script output, source: https://alestic.com/2010/12/ec2-user-data-output/
exec > >(tee -a /var/log/download-files.log | logger -t user-data -s 2>/dev/console) 2>&1
echo -----
echo ----- start script
echo -----

echo ----- update system -----

INDICATOR=/var/tmp/indicator-update-system
if [ ! -f "${INDICATOR}" ]; then
    apt-get update
    apt-get upgrade -y
    touch "${INDICATOR}"
fi

echo ----- install CloudWatch agent -----

INDICATOR=/var/tmp/indicator-cloudwatch-agent
if [ ! -f "${INDICATOR}" ]; then
    wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/arm64/latest/amazon-cloudwatch-agent.deb
    #wget https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
    dpkg -i -E amazon-cloudwatch-agent.deb
    amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c ssm:/ONT-performance-benchmark/downloader-cloudwatch-agent-config
    service awslogs start
    touch "${INDICATOR}"
fi

echo ----- reset status parameters -----

INDICATOR=/var/tmp/indicator-reset-status-parameters
if [ ! -f "${INDICATOR}" ]; then
    aws ssm put-parameter --name /ONT-performance-benchmark/download-status --value "not started" --overwrite --output text
    aws ssm put-parameter --name /ONT-performance-benchmark/pod5-converter-status --value "not started" --overwrite --output text
    touch "${INDICATOR}"
fi

echo ----- install FSx for Lustre client -----

INDICATOR=/var/tmp/indicator-install-kernel
if [ ! -f "${INDICATOR}" ]; then
    wget -O - https://fsx-lustre-client-repo-public-keys.s3.amazonaws.com/fsx-ubuntu-public-key.asc | gpg --dearmor | sudo tee /usr/share/keyrings/fsx-ubuntu-public-key.gpg >/dev/null
    bash -c 'echo "deb [signed-by=/usr/share/keyrings/fsx-ubuntu-public-key.gpg] https://fsx-lustre-client-repo.s3.amazonaws.com/ubuntu jammy main" > /etc/apt/sources.list.d/fsxlustreclientrepo.list && apt-get update'
    version="6.2.0-1018-aws"
    apt-get install -y linux-image-"$version"
    sed -i 's/GRUB_DEFAULT=.\+/GRUB\_DEFAULT="Advanced options for Ubuntu>Ubuntu, with Linux '$version'"/' /etc/default/grub
    update-grub
    touch "${INDICATOR}"
    echo "Reboot to activate installed kernel."
    shutdown -r now
    sleep 60
fi

INDICATOR=/var/tmp/indicator-install-fsx-lustre
if [ ! -f "${INDICATOR}" ]; then
    apt-get install -y linux-aws lustre-client-modules-"$(uname -r)"
    touch "${INDICATOR}"
    echo "Reboot to activate FSX Lustre client."
    shutdown -r now
    sleep 60
fi

echo ----- install Pod5 -----

INDICATOR=/var/tmp/indicator-install-pod5
if [ ! -f "${INDICATOR}" ]; then
    apt-get install python3-pip -y
    pip install pod5
    pip install pandas
    touch "${INDICATOR}"
fi

echo ----- get token to access instance metadata -----

TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
instance_id=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
region=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/dynamic/instance-identity/document | jq --raw-output .region)
fsx_dns_mount_name=$(eval '/usr/local/bin/aws ssm get-parameters --region '"$region"' --names /ONT-performance-benchmark/fsx-lustre-dns-mount-name --query '"'"'Parameters[0].Value'"'"' --output text')

echo ----- mount FSx for Lustre file system -----

mkdir -p /fsx
mount -t lustre -o noatime,flock "${fsx_dns_mount_name}" /fsx

echo ----- download test data -----

INDICATOR=/var/tmp/indicator-download-test-data
if [ ! -f "${INDICATOR}" ]; then
    # DISCLAIMER: The download URL is from the CliveOME 5mC dataset (ONLA29134 size: 745.4 GiB). A FAST5 data set published by
    # Oxford Nanopore Technologies. For more details about the data set, please see
    # https://labs.epi2me.io/cliveome_5mc_cfdna_celldna/
    download_url='s3://ont-open-data/cliveome_kit14_2022.05/gdna/flowcells/ONLA29134/20220510_1127_5H_PAM63974_a5e7a202/fast5_pass/'

    files_to_download=($(aws s3 ls $download_url --no-sign-request | awk '{print $4}' | sort -n -t _ -k 4))
    local_s3_url=$(eval 'aws ssm get-parameters --names /ONT-performance-benchmark/data-s3-bucket --query '"'"'Parameters[0].Value'"'"' --output text')
    aws ssm put-parameter --name /ONT-performance-benchmark/download-status --value "in progress" --overwrite --output text
    for ((i = 0; i < ${#files_to_download[@]}; ++i)); do
        current=$(( i + 1 ))
        echo "$current/${#files_to_download[@]}: ${files_to_download[$i]}"
        aws s3 cp "$download_url${files_to_download[$i]}" - --no-sign-request | aws s3 cp - "s3://$local_s3_url/fast5-all-files/${files_to_download[$i]}"
    done
    aws ssm put-parameter --name /ONT-performance-benchmark/download-status --value "completed" --overwrite --output text
    touch "${INDICATOR}"
fi

echo ----- convert FAST5 to POD5 -----

INDICATOR=/var/tmp/indicator-convert-fast5-to-pod5
if [ ! -f "${INDICATOR}" ]; then
    ## For details about how top convert FAST5 to POD5 please see
    ## https://github.com/nanoporetech/pod5-file-format/blob/master/python/pod5/README.md
    aws ssm put-parameter --name /ONT-performance-benchmark/pod5-converter-status --value "in progress" --overwrite --output text
    num_fast5_files=$(find /fsx/fast5-all-files -name "*.fast5" | wc -l)
    echo "Total number of fast5 files: ${num_fast5_files}"
    pod5 convert fast5 /fsx/fast5-all-files/*.fast5 --output /fsx/pod5-all-files/ --one-to-one /fsx/fast5-all-files/ --threads 20 --strict --force-overwrite
    aws ssm put-parameter --name /ONT-performance-benchmark/pod5-converter-status --value "completed" --overwrite --output text
    touch "${INDICATOR}"
fi

echo ----- create test data sets -----

INDICATOR=/var/tmp/indicator-create-test-data-sets
if [ ! -f "${INDICATOR}" ]; then
    script_file=$(eval '/usr/local/bin/aws ssm get-parameters --region '"$region"' --names /ONT-performance-benchmark/pod5-create-test-data-script --query '"'"'Parameters[0].Value'"'"' --output text')
    aws s3 cp "$script_file" create_test_data_sets.py
    python3 create_test_data_sets.py
    touch "${INDICATOR}"
fi

echo ----- check download and conversion results -----

num_pod5_files=$(find /fsx/pod5-all-files -name "*.pod5" | wc -l)
echo "$num_fast5_files FAST5 files downloaded and converted to $num_pod5_files POD5 files."
if [[ $num_fast5_files -eq $num_pod5_files ]] && [[ $num_fast5_files -gt 0 ]]; then
  echo "OK: Download and conversion successful."
else
  echo "ERROR: A problem occurred during download and conversion. The number of FAST5 and POD5 files don't match."
fi

echo ----- delete downloader CloudFormation stack -----

cf_stack_name=$(eval '/usr/local/bin/aws ssm get-parameters --region '"$region"' --names /ONT-performance-benchmark/downloader-stack-name --query '"'"'Parameters[0].Value'"'"' --output text')
aws cloudformation delete-stack --stack-name "$cf_stack_name"

echo -----
echo ----- end UserData script -----
echo -----

shutdown now
