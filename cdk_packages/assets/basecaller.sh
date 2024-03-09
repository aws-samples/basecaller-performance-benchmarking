#!/bin/bash

echo "Basecaller script started."

container_start_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")

function get_container_value() {
  result=$(aws batch describe-jobs --jobs "$AWS_BATCH_JOB_ID" --query "jobs[0].container.resourceRequirements[$index].value" --region "$REGION" --output text)
  echo "$result"
}

function get_container_type() {
  result=$(aws batch describe-jobs --jobs "$AWS_BATCH_JOB_ID" --query "jobs[0].container.resourceRequirements[$index].type" --region "$REGION" --output text)
  echo "$result"
}

echo "AWS Batch job ID: $AWS_BATCH_JOB_ID"
echo "data set ID: $DATA_SET_ID"
echo "compute environment: $AWS_BATCH_CE_NAME"
echo "region: $REGION"

# Get ID of EC2 instance on which this job runs.
container_instance_arn=$(aws batch describe-jobs --jobs "$AWS_BATCH_JOB_ID" --query "jobs[0].container.containerInstanceArn" --output text)
tmp=${container_instance_arn#*/}
cluster_name=${tmp%/*}
ec2_instance_id=$(aws ecs describe-container-instances --container-instances "$container_instance_arn" --cluster "$cluster_name" --query "containerInstances[0].ec2InstanceId" --output text)
echo "EC2 instance ID: $ec2_instance_id"

# Get EC2 instance launch time.
ec2_instance_launch_time=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$ec2_instance_id" --query "Reservations[0].Instances[0].LaunchTime" --output text)

# Get container sizing parameters such as vCPUs, GPUs and memory.
index=0
type=$(get_container_type)
container_param1_type="container_${type}"
container_param1_value=$(get_container_value)
index=1
type=$(get_container_type)
container_param2_type="container_${type}"
container_param2_value=$(get_container_value)
index=2
type=$(get_container_type)
container_param3_type="container_${type}"
container_param3_value=$(get_container_value)

# split command and parameters
shopt -s extglob
received_cmd_line=$1
command=$(grep -oP "^\S+" <<< "$received_cmd_line")
parameters=${received_cmd_line#@($command)}

# Add job ID to guppy save path
if [ "$command" == "guppy_basecaller" ]; then
  first_part=$(grep -oP ".*--save_path\s+\S+" <<< "$parameters")
  second_part=${parameters//$first_part}
  parameters=$first_part$AWS_BATCH_JOB_ID"/ "$second_part
fi

# Add job ID to dorado save path
if [ "$command" == "dorado" ]; then
  mkdir -p /fsx/out/"$AWS_BATCH_JOB_ID"
  parameters="${parameters/&job_id&/${AWS_BATCH_JOB_ID}}"
fi

# Create entry in results table.
reports_table=$(aws ssm get-parameters --region "$REGION" --names /ONT-performance-benchmark/reports-table-name --query "Parameters[0].Value" --output text)
aws dynamodb put-item --table-name "$reports_table" \
  --item '{
        "job_id": {"S": "'"$AWS_BATCH_JOB_ID"'"},
        "data_set_id": {"S": "'"$DATA_SET_ID"'"},
        "container_start_time": {"S": "'"$container_start_time"'"},
        "status": {"S": "started"},
        "compute_environment": {"S": "'"$AWS_BATCH_CE_NAME"'"},
        "ec2_instance_id": {"S": "'"$ec2_instance_id"'"},
        "ec2_instance_launch_time": {"S": "'"$ec2_instance_launch_time"'"},
        "job_attempts": {"N": "'"$AWS_BATCH_JOB_ATTEMPT"'"},
        "parameters": {"S": "'"$received_cmd_line"'"},
        "'"$container_param1_type"'": {"N": "'"$container_param1_value"'"},
        "'"$container_param2_type"'": {"N": "'"$container_param2_value"'"},
        "'"$container_param3_type"'": {"N": "'"$container_param3_value"'"},
        "tags": {"S": "'"$TAGS"'"}
      }' \
  --region "$REGION"

# ---------- run basecaller --------------------
echo "starting basecaller:"
echo "$command$parameters"
basecaller_name=""
basecaller_version=""
if [ "$command" == "guppy_basecaller" ]; then
  basecaller_name="guppy"
  basecaller_version=$(guppy_basecaller --version | grep -oP "(?<=Version )[0-9]+\.[0-9]+\.[0-9]+")
  echo "basecaller: $basecaller_name v$basecaller_version"
  # Do not place $parameters in quotation marks! Will cause "Unexpected token '[...]' on command-line" error.
  guppy_basecaller $parameters |& tee guppy_basecaller.log
  ret="${PIPESTATUS[0]}"
fi
if [ "$command" == "dorado" ]; then
  basecaller_name="dorado"
  basecaller_version=$(eval "dorado --version" |& grep -oP "[0-9]+\.[0-9]+\.[0-9]+")
  echo "basecaller: $basecaller_name v$basecaller_version"
  eval "dorado""$parameters" |& tee dorado.log
  ret="${PIPESTATUS[0]}"
fi
echo "return code from basecaller = $ret"
# ----------------------------------------------

container_end_time=$(date -u +"%Y-%m-%dT%H:%M:%S%:z")

# Update entry in results DynamoDB table with measurement data
echo "writing results to reports table: $reports_table"
if [ "$ret" != 0 ]; then
  status="failed"
  aws dynamodb put-item --table-name "$reports_table" \
    --item '{
          "job_id": {"S": "'"$AWS_BATCH_JOB_ID"'"},
          "data_set_id": {"S": "'"$DATA_SET_ID"'"},
          "container_start_time": {"S": "'"$container_start_time"'"},
          "container_end_time": {"S": "'"$container_end_time"'"},
          "status": {"S": "'"$status"'"},
          "compute_environment": {"S": "'"$AWS_BATCH_CE_NAME"'"},
          "ec2_instance_id": {"S": "'"$ec2_instance_id"'"},
          "ec2_instance_launch_time": {"S": "'"$ec2_instance_launch_time"'"},
          "job_attempts": {"N": "'"$AWS_BATCH_JOB_ATTEMPT"'"},
          "parameters": {"S": "'"$received_cmd_line"'"},
          "'"$container_param1_type"'": {"N": "'"$container_param1_value"'"},
          "'"$container_param2_type"'": {"N": "'"$container_param2_value"'"},
          "'"$container_param3_type"'": {"N": "'"$container_param3_value"'"},
          "tags": {"S": "'"$TAGS"'"}
        }' \
    --region "$REGION"
else
  status="succeeded"
  if [ "$command" == "guppy_basecaller" ]; then
    caller_time_ms=$(grep -oP "(?<=Caller time: )[0-9]+" guppy_basecaller.log)
    samples_called=$(grep -oP "(?<=Samples called: )[0-9]+" guppy_basecaller.log)
    samples_per_s=$(grep -oP "(?<=samples/s: )[0-9]+\.[0-9]+e\+[0-9]+" guppy_basecaller.log)
  fi
  if [ "$command" == "dorado" ]; then
    selected_batch_size=$(grep -oP "(?<=selected batchsize )[0-9]+" dorado.log)
    reads_basecalled=$(grep -oP "(?<=Reads basecalled: )[0-9]+" dorado.log)
    samples_per_s=$(grep -oP "(?<=Samples/s: )[0-9]+\.[0-9]+e\+[0-9]+" dorado.log)
  fi
  aws dynamodb put-item --table-name "$reports_table" \
    --item '{
          "job_id": {"S": "'"$AWS_BATCH_JOB_ID"'"},
          "data_set_id": {"S": "'"$DATA_SET_ID"'"},
          "container_start_time": {"S": "'"$container_start_time"'"},
          "container_end_time": {"S": "'"$container_end_time"'"},
          "status": {"S": "'"$status"'"},
          "compute_environment": {"S": "'"$AWS_BATCH_CE_NAME"'"},
          "ec2_instance_id": {"S": "'"$ec2_instance_id"'"},
          "ec2_instance_launch_time": {"S": "'"$ec2_instance_launch_time"'"},
          "job_attempts": {"N": "'"$AWS_BATCH_JOB_ATTEMPT"'"},
          "parameters": {"S": "'"$received_cmd_line"'"},
          "'"$container_param1_type"'": {"N": "'"$container_param1_value"'"},
          "'"$container_param2_type"'": {"N": "'"$container_param2_value"'"},
          "'"$container_param3_type"'": {"N": "'"$container_param3_value"'"},
          "tags": {"S": "'"$TAGS"'"},
          "basecaller_name": {"S": "'"$basecaller_name"'"},
          "basecaller_version": {"S": "'"$basecaller_version"'"},
          "caller_time_ms": {"S": "'"$caller_time_ms"'"},
          "samples_called": {"S": "'"$samples_called"'"},
          "samples_per_s": {"S": "'"$samples_per_s"'"},
          "selected_batch_size": {"S": "'"$selected_batch_size"'"},
          "reads_basecalled": {"S": "'"$reads_basecalled"'"}
        }' \
    --region "$REGION"
fi

# Give it a few seconds for the last messages to be captured by CloudWatch log.
# The EC2 instance is shutdown immediately and often the last lines from the
# basecaller log are missing in CloudWatch.
sleep 10

echo "job completed"
exit "$ret"
