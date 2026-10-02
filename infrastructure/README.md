# v0.6.0 Infrastructure

本版本没有 Infrastructure-as-Code change。

不需要创建、更新或删除 CloudFormation stack，也不需要修改：

- `home-energy-collector`；
- EventBridge / Scheduler；
- legacy historian table；
- `home-energy-telemetry` table/schema；
- Lightsail instance、systemd service 或 IAM writer identity。

`source/infrastructure.yaml` 与 `source/infrastructure-fast-telemetry/template.yaml` 只作为现有 architecture reference 保留，不能作为 v0.6.0 deployment step。若任何 change set 显示上述 production resources 将被修改，请停止部署。
