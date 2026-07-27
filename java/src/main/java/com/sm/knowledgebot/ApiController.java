package com.sm.knowledgebot;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@RestController
@CrossOrigin(origins = "*")
public class ApiController {
  private final String jdbcUrl;
  private final ObjectMapper mapper = new ObjectMapper();
  private final HttpClient http = HttpClient.newHttpClient();
  private static final Map<String, Integer> LEVEL = Map.of("employee", 1, "manager", 2, "admin", 3);

  public ApiController(@Value("${app.database-path}") String path) throws Exception {
    Files.createDirectories(Path.of(path).getParent()); jdbcUrl = "jdbc:sqlite:" + path; initialize(); seedGuide();
  }
  private Connection db() throws SQLException { return DriverManager.getConnection(jdbcUrl); }
  private void initialize() throws SQLException {
    try (Connection c=db(); Statement s=c.createStatement()) {
      s.executeUpdate("CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT,role TEXT,department TEXT)");
      s.executeUpdate("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT,department TEXT,min_role TEXT,created_by TEXT,created_at TEXT)");
      s.executeUpdate("CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,document_id TEXT,content TEXT)");
      s.executeUpdate("CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,user_id TEXT,created_at TEXT)");
      s.executeUpdate("CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT,role TEXT,content TEXT,created_at TEXT)");
      s.executeUpdate("INSERT OR IGNORE INTO users VALUES('admin','系统管理员','admin','all')");
    }
  }
  private void seedGuide() throws SQLException {
    String title="示例：SM Knowledge Bot 操作指南";
    try(Connection c=db(); PreparedStatement exists=c.prepareStatement("SELECT id FROM documents WHERE title=?")) {
      exists.setString(1,title); ResultSet result=exists.executeQuery();
      if(result.next()) {
        try(PreparedStatement removeChunks=c.prepareStatement("DELETE FROM chunks WHERE document_id=?"); PreparedStatement removeDocument=c.prepareStatement("DELETE FROM documents WHERE id=?")) {
          removeChunks.setString(1,result.getString("id")); removeChunks.executeUpdate();
          removeDocument.setString(1,result.getString("id")); removeDocument.executeUpdate();
        }
      }
      String id=UUID.randomUUID().toString();
      String content="""
        SM Knowledge Bot 操作指南（内置模拟文件）

        1. 启动服务：进入 java 目录后执行 .\\start-java.ps1，服务默认监听 http://127.0.0.1:8080。
        2. 检查状态：在浏览器或终端访问 GET /health，返回 status=ok 表示服务已启动。
        3. 安装全部 Skill（推荐）：npx skills add https://github.com/Unclecheng-li/AI_Animation。
        4. 安装单个 Skill：npx skills add https://github.com/Unclecheng-li/AI_Animation/tree/main/skills/ppt-animation。其余可选目录包括 flowchart、network-protocol-viz、dynamic-archify 和 scholar-notes。
        5. 安装项目：git clone https://github.com/StavinLi/Workflow.git；进入目录后按照该项目 README 执行安装命令。
        6. 同步到知识库：以管理员身份向 POST /documents/import/github 提交 repository_url、department 和可选 branch。示例仓库地址为 https://github.com/Unclecheng-li/AI_Animation。
        7. 提问：向 POST /chat 提交 question；必须使用 X-User-Id 请求头。首次可使用 admin。接口会返回 conversation_id；下一轮问题携带该 conversation_id 即可连续对话。
        8. 权限：employee 只能问答；manager 和 admin 可以录入文档、同步 GitHub。admin 还可以通过 POST /users 创建用户。
        """;
      try(PreparedStatement d=c.prepareStatement("INSERT INTO documents VALUES(?,?,?,?,?,?)"); PreparedStatement q=c.prepareStatement("INSERT INTO chunks VALUES(?,?,?)")) {
        d.setString(1,id);d.setString(2,title);d.setString(3,"all");d.setString(4,"employee");d.setString(5,"admin");d.setString(6,Instant.now().toString());d.executeUpdate();
        q.setString(1,UUID.randomUUID().toString());q.setString(2,id);q.setString(3,content);q.executeUpdate();
      }
    }
  }
  record User(String id,String name,String role,String department) {}
  record DocumentRequest(String title,String content,String department,String min_role) {}
  record ChatRequest(String question,String conversation_id) {}
  record GithubRequest(String repository_url,String branch,String department,String min_role,Integer max_files) {}
  private User user(String id) throws SQLException {
    if(id==null || id.isBlank()) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"请提供 X-User-Id");
    try(Connection c=db(); PreparedStatement s=c.prepareStatement("SELECT * FROM users WHERE id=?")){s.setString(1,id); ResultSet r=s.executeQuery(); if(!r.next())throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"用户不存在"); return new User(r.getString("id"),r.getString("name"),r.getString("role"),r.getString("department"));}
  }
  private User requireManager(String id) throws SQLException { User u=user(id); if(LEVEL.get(u.role())<2)throw new ResponseStatusException(HttpStatus.FORBIDDEN,"需要经理或管理员权限"); return u; }
  @GetMapping("/health") Map<String,String> health(){return Map.of("status","ok","version","java-1.1.0");}
  @GetMapping("/api/summary") Map<String,Object> summary(@RequestHeader("X-User-Id") String id) throws SQLException { user(id); try(Connection c=db(); Statement s=c.createStatement()){ResultSet d=s.executeQuery("SELECT COUNT(*) count FROM documents"); int documents=d.next()?d.getInt("count"):0; ResultSet q=s.executeQuery("SELECT COUNT(*) count FROM chunks"); int chunks=q.next()?q.getInt("count"):0; return Map.of("documents",documents,"chunks",chunks,"user",id);}}
  @PostMapping("/users") Map<String,String> createUser(@RequestHeader("X-User-Id") String actor,@RequestBody User input) throws SQLException {if(!user(actor).role().equals("admin"))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"需要管理员权限");try(Connection c=db();PreparedStatement s=c.prepareStatement("INSERT INTO users VALUES(?,?,?,?)")){s.setString(1,input.id());s.setString(2,input.name());s.setString(3,input.role());s.setString(4,input.department());s.executeUpdate();}return Map.of("id",input.id(),"message","用户已创建");}
  @PostMapping("/documents") Map<String,Object> document(@RequestHeader("X-User-Id") String id,@RequestBody DocumentRequest input) throws SQLException {User u=requireManager(id);String did=UUID.randomUUID().toString();List<String> chunks=split(input.content());try(Connection c=db()){try(PreparedStatement d=c.prepareStatement("INSERT INTO documents VALUES(?,?,?,?,?,?)")){d.setString(1,did);d.setString(2,input.title());d.setString(3,Optional.ofNullable(input.department()).orElse("all"));d.setString(4,Optional.ofNullable(input.min_role()).orElse("employee"));d.setString(5,u.id());d.setString(6,Instant.now().toString());d.executeUpdate();}try(PreparedStatement q=c.prepareStatement("INSERT INTO chunks VALUES(?,?,?)")){for(String chunk:chunks){q.setString(1,UUID.randomUUID().toString());q.setString(2,did);q.setString(3,chunk);q.addBatch();}q.executeBatch();}}return Map.of("id",did,"chunks",chunks.size(),"message","文档已索引");}
  @PostMapping("/chat") Map<String,Object> chat(@RequestHeader("X-User-Id") String id,@RequestBody ChatRequest input) throws SQLException {User u=user(id);if(input.question()==null||input.question().isBlank())throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"问题不能为空");String cid=input.conversation_id()==null?UUID.randomUUID().toString():input.conversation_id();List<Map<String,String>> hits=search(input.question(),u);String answer=hits.isEmpty()?"当前权限范围内没有检索到相关知识。":String.join("\n\n",hits.stream().map(x->"《"+x.get("title")+"》\n"+x.get("content")).toList());try(Connection c=db();PreparedStatement owner=c.prepareStatement("SELECT user_id FROM conversations WHERE id=?");PreparedStatement cs=c.prepareStatement("INSERT OR IGNORE INTO conversations VALUES(?,?,?)");PreparedStatement ms=c.prepareStatement("INSERT INTO messages VALUES(?,?,?,?,?)")){owner.setString(1,cid);ResultSet existing=owner.executeQuery();if(existing.next()&&!existing.getString("user_id").equals(u.id())&&!u.role().equals("admin"))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"无权访问该会话");cs.setString(1,cid);cs.setString(2,u.id());cs.setString(3,Instant.now().toString());cs.executeUpdate();for(String[] m:new String[][]{{"user",input.question()},{"assistant",answer}}){ms.setString(1,UUID.randomUUID().toString());ms.setString(2,cid);ms.setString(3,m[0]);ms.setString(4,m[1]);ms.setString(5,Instant.now().toString());ms.addBatch();}ms.executeBatch();}return Map.of("conversation_id",cid,"answer",answer,"sources",hits);}
  @PostMapping("/documents/import/github") Map<String,Object> github(@RequestHeader("X-User-Id") String id,@RequestBody GithubRequest input) throws Exception {User u=requireManager(id);Matcher m=Pattern.compile("(?:https://github\\.com/|git@github\\.com:)([\\w.-]+)/([\\w.-]+?)(?:\\.git)?/?$").matcher(input.repository_url());if(!m.find())throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"GitHub URL 格式错误");String owner=m.group(1),repo=m.group(2),branch=input.branch()==null?"main":input.branch();HttpRequest rq=HttpRequest.newBuilder(URI.create("https://api.github.com/repos/"+owner+"/"+repo+"/git/trees/"+branch+"?recursive=1")).header("Accept","application/vnd.github+json").build();JsonNode tree=mapper.readTree(http.send(rq,HttpResponse.BodyHandlers.ofString()).body()).path("tree");int files=0,chunks=0,max=input.max_files()==null?50:input.max_files();for(JsonNode item:tree){String path=item.path("path").asText();if(files>=max||!item.path("type").asText().equals("blob")||!path.matches(".*\\.(md|txt|rst|java|py|js|ts|json|ya?ml)$"))continue;HttpResponse<String> source=http.send(HttpRequest.newBuilder(URI.create("https://raw.githubusercontent.com/"+owner+"/"+repo+"/"+branch+"/"+path)).build(),HttpResponse.BodyHandlers.ofString());if(source.statusCode()<300&&!source.body().isBlank()){DocumentRequest d=new DocumentRequest("github:"+owner+"/"+repo+":"+path,source.body(),Optional.ofNullable(input.department()).orElse("all"),Optional.ofNullable(input.min_role()).orElse("employee"));document(id,d);files++;chunks+=split(source.body()).size();}}return Map.of("repository",owner+"/"+repo,"branch",branch,"files",files,"chunks",chunks);}
  private List<String> split(String text){List<String> out=new ArrayList<>();for(int i=0;i<text.length();i+=500)out.add(text.substring(i,Math.min(i+500,text.length())));return out;}
  private Set<String> terms(String s){return new HashSet<>(Arrays.asList(s.toLowerCase().split("[^a-zA-Z0-9\\u4e00-\\u9fff]+")));}
  private List<Map<String,String>> search(String question,User u)throws SQLException{Set<String> q=terms(question);List<Map<String,String>> all=new ArrayList<>();try(Connection c=db();Statement s=c.createStatement();ResultSet r=s.executeQuery("SELECT d.id,d.title,d.department,d.min_role,c.content FROM documents d JOIN chunks c ON d.id=c.document_id")){while(r.next()){if(LEVEL.get(u.role())<LEVEL.get(r.getString("min_role"))||(!r.getString("department").equals("all")&&!r.getString("department").equals(u.department())&&!u.role().equals("admin")))continue;Set<String> t=terms(r.getString("content"));t.retainAll(q);if(!t.isEmpty())all.add(Map.of("document_id",r.getString("id"),"title",r.getString("title"),"content",r.getString("content"),"score",String.valueOf(t.size())));}}all.sort((a,b)->Integer.compare(Integer.parseInt(b.get("score")),Integer.parseInt(a.get("score"))));return all.stream().limit(4).toList();}
}
