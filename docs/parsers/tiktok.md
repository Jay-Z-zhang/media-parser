# TikTok 解析与创作者订阅

* **平台标识**：`TikTok`
* **支持**：公开短视频标题、作者、封面、播放直链
* **Cookie**：公开主页与公开作品默认免登录
* **常见链接**：
  * `https://www.tiktok.com/@user/video/{id}`
  * `https://vm.tiktok.com/xxxx/`
  * 创作者主页 `https://www.tiktok.com/@user`

从页面 `__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` 提取 `itemStruct`。创作者订阅走 `python -m src.watch`，会列出主页最近作品再下载。
