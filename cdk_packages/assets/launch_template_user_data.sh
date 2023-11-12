MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="==MYBOUNDARY=="

--==MYBOUNDARY==
MIME-Version: 1.0
Content-Type: text/x-shellscript; charset="us-ascii"

#!/bin/bash
rm -rf /var/log/ecs/*
rm -rf /var/lib/ecs/data/*
echo ECS_ENABLE_GPU_SUPPORT=true>>/etc/ecs/ecs.config
echo ECS_NVIDIA_RUNTIME=nvidia>>/etc/ecs/ecs.config
systemctl enable ecs --now

--==MYBOUNDARY==--
