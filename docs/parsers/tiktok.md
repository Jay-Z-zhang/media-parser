# TikTok 解析与创作者订阅

* **平台标识**：`TikTok`
* **支持**：公开短视频标题、作者、封面、播放直链
* **Cookie**：公开主页与公开作品默认免登录
* **常见链接**：
  * `https://www.tiktok.com/@user/video/{id}`
  * `https://vm.tiktok.com/xxxx/`
  * 创作者主页 `https://www.tiktok.com/@user`

从页面 `__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` 提取 `itemStruct`。下载优先用网页绿色下载按钮对应的 `video.downloadAddr`，并且必须带着打开作品页后的 Cookie（`ttwid` / `msToken` 等）；对 CDN 冷请求会 403。创作者订阅走 `python -m src.watch`。
