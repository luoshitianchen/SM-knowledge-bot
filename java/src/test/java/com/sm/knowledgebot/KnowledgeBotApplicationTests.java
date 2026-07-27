package com.sm.knowledgebot;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "app.database-path=target/test-knowledge-bot.db")
class KnowledgeBotApplicationTests {
  @Test void contextLoads() { }
}
