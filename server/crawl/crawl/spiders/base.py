"""scrapy-redis 基类：按 site_group 隔离种子队列。"""

from scrapy_redis.spiders import RedisSpider


class BaseRedisSpider(RedisSpider):
    """按 site_group 生成 redis_key 的 RedisSpider。

    种子队列：``ecom:sc:{site_group}:requests``。
    """

    site_group = "default"

    def __init__(self, site_group: str = "default", *args, **kwargs):
        self.site_group = site_group or "default"
        super().__init__(*args, **kwargs)
        self.redis_key = f"ecom:sc:{self.site_group}:requests"
