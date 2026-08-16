# 设计文档索引

- [总体架构与安全自进化](architecture.md)：Channel、可插拔 Harness、上下文迁移、Tool Broker、执行环境和发布回滚。
- [DeepSeek Harness、Hermes Agent 与 Prime Agent 调研](harness-self-evolution-research.md)：三套源码的自进化机制、边界、对比和本项目采用建议。
- [可控的持续学习与自进化](controlled-learning-design.md)：分别展示三套 Harness 的进化闭环，并说明如何组合成越聊越聪明、可评测和可回滚的系统。
- [落地实施方案](implementation-plan.md)：当前实现审计、模块接口、数据模型、三套 Runtime 接入、阶段计划和验收标准。
- [微信异步任务与消息推送](wechat-async-delivery.md)：可解释 ETA、SQLite 持久队列、Worker 租约、客服消息推送和无权限回退。

这些文档描述目标架构；当前代码只实现其中的早期骨架，不能把设计中的安全保证视为已经完成。
