from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "football"

    # API-Football
    api_football_key: str = ""
    api_football_base_url: str = ""

    # football-data.co.uk（免费 CSV 数据源，无需 key）
    # 用于回填历史比赛与统计，节省 API-Football 的每日配额
    football_data_base_url: str = "https://www.football-data.co.uk/mmz4281"

    # Understat（免费真实 xG 数据源，无需 key）
    # 用于回填 fixture_statistics.expected_goals，供 B 组 xg 特征使用
    understat_base_url: str = "https://understat.com/getLeagueData"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # 缓存
    cache_ttl: int = 3600

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
