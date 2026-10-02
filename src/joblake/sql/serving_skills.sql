SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(741205,1);
-- Generated from joblake.skills/catalogue.json. Version 2026-10-02.1.
CREATE OR REPLACE FUNCTION serving.skill_key(value text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT CASE lower(regexp_replace(btrim(normalize(value,NFC)), '[[:space:]]+', ' ', 'g'))
 WHEN '.net' THEN 'dotnet'
 WHEN '.net core' THEN 'dotnet-core'
 WHEN '3d studio max' THEN '3dsmax'
 WHEN '3ds max' THEN '3dsmax'
 WHEN 'active directory' THEN 'active-directory'
 WHEN 'adobe after effects' THEN 'after-effects'
 WHEN 'adobe illustrator' THEN 'illustrator'
 WHEN 'adobe indesign' THEN 'indesign'
 WHEN 'adobe photoshop' THEN 'photoshop'
 WHEN 'adobe premiere pro' THEN 'premiere-pro'
 WHEN 'after effects' THEN 'after-effects'
 WHEN 'agile' THEN 'agile'
 WHEN 'ai' THEN 'ai'
 WHEN 'airflow' THEN 'airflow'
 WHEN 'amazon web services' THEN 'aws'
 WHEN 'android' THEN 'android'
 WHEN 'angular' THEN 'angular'
 WHEN 'ansible' THEN 'ansible'
 WHEN 'apache airflow' THEN 'airflow'
 WHEN 'apache http server' THEN 'apache'
 WHEN 'apache kafka' THEN 'kafka'
 WHEN 'apache spark' THEN 'spark'
 WHEN 'api' THEN 'api'
 WHEN 'api testing' THEN 'api-testing'
 WHEN 'argo cd' THEN 'argocd'
 WHEN 'argocd' THEN 'argocd'
 WHEN 'artificial intelligence' THEN 'ai'
 WHEN 'asp.net' THEN 'aspnet'
 WHEN 'asp.net core' THEN 'aspnet-core'
 WHEN 'autocad' THEN 'autocad'
 WHEN 'aws' THEN 'aws'
 WHEN 'azure' THEN 'azure'
 WHEN 'azure devops' THEN 'azure-devops'
 WHEN 'b2b sales' THEN 'b2b-sales'
 WHEN 'bash' THEN 'bash'
 WHEN 'big data' THEN 'big-data'
 WHEN 'bigquery' THEN 'bigquery'
 WHEN 'blender' THEN 'blender'
 WHEN 'bootstrap' THEN 'bootstrap'
 WHEN 'bpmn' THEN 'bpmn'
 WHEN 'brd' THEN 'brd'
 WHEN 'business analysis' THEN 'business-analysis'
 WHEN 'bán hàng' THEN 'sales'
 WHEN 'c' THEN 'c'
 WHEN 'c#' THEN 'csharp'
 WHEN 'c++' THEN 'cplusplus'
 WHEN 'canva' THEN 'canva'
 WHEN 'capcut' THEN 'capcut'
 WHEN 'chatgpt' THEN 'chatgpt'
 WHEN 'chinese' THEN 'chinese'
 WHEN 'chăm sóc khách hàng' THEN 'customer-service'
 WHEN 'ci/cd' THEN 'cicd'
 WHEN 'claude' THEN 'claude'
 WHEN 'confluence' THEN 'confluence'
 WHEN 'content marketing' THEN 'content-marketing'
 WHEN 'copywriting' THEN 'copywriting'
 WHEN 'cpp' THEN 'cplusplus'
 WHEN 'crm' THEN 'crm'
 WHEN 'csharp' THEN 'csharp'
 WHEN 'cskh' THEN 'customer-service'
 WHEN 'css' THEN 'css'
 WHEN 'css3' THEN 'css3'
 WHEN 'cypress' THEN 'cypress'
 WHEN 'dart' THEN 'dart'
 WHEN 'data analysis' THEN 'data-analysis'
 WHEN 'data modeling' THEN 'data-modeling'
 WHEN 'data warehouse' THEN 'data-warehouse'
 WHEN 'databricks' THEN 'databricks'
 WHEN 'dbt' THEN 'dbt'
 WHEN 'design patterns' THEN 'design-patterns'
 WHEN 'design system' THEN 'design-system'
 WHEN 'devops' THEN 'devops'
 WHEN 'devsecops' THEN 'devsecops'
 WHEN 'digital marketing' THEN 'digital-marketing'
 WHEN 'django' THEN 'django'
 WHEN 'dns' THEN 'dns'
 WHEN 'docker' THEN 'docker'
 WHEN 'dotnet' THEN 'dotnet'
 WHEN 'dotnet core' THEN 'dotnet-core'
 WHEN 'elasticsearch' THEN 'elasticsearch'
 WHEN 'english' THEN 'english'
 WHEN 'erp' THEN 'erp'
 WHEN 'etl' THEN 'etl'
 WHEN 'excel' THEN 'excel'
 WHEN 'express' THEN 'express'
 WHEN 'express.js' THEN 'express'
 WHEN 'expressjs' THEN 'express'
 WHEN 'facebook ads' THEN 'facebook-ads'
 WHEN 'fastapi' THEN 'fastapi'
 WHEN 'figma' THEN 'figma'
 WHEN 'financial analysis' THEN 'financial-analysis'
 WHEN 'firebase' THEN 'firebase'
 WHEN 'flask' THEN 'flask'
 WHEN 'flutter' THEN 'flutter'
 WHEN 'gcp' THEN 'gcp'
 WHEN 'giao tiếp' THEN 'communication'
 WHEN 'git' THEN 'git'
 WHEN 'github' THEN 'github'
 WHEN 'github actions' THEN 'github-actions'
 WHEN 'gitlab' THEN 'gitlab'
 WHEN 'gitlab ci' THEN 'gitlab-ci'
 WHEN 'go' THEN 'go'
 WHEN 'golang' THEN 'go'
 WHEN 'google ads' THEN 'google-ads'
 WHEN 'google analytics' THEN 'google-analytics'
 WHEN 'google cloud platform' THEN 'gcp'
 WHEN 'google sheets' THEN 'google-sheets'
 WHEN 'grafana' THEN 'grafana'
 WHEN 'graphql' THEN 'graphql'
 WHEN 'grpc' THEN 'grpc'
 WHEN 'hadoop' THEN 'hadoop'
 WHEN 'helm' THEN 'helm'
 WHEN 'hive' THEN 'hive'
 WHEN 'hrm' THEN 'hrm'
 WHEN 'html' THEN 'html'
 WHEN 'html5' THEN 'html5'
 WHEN 'illustrator' THEN 'illustrator'
 WHEN 'indesign' THEN 'indesign'
 WHEN 'ios' THEN 'ios'
 WHEN 'iso 27001' THEN 'iso27001'
 WHEN 'iso27001' THEN 'iso27001'
 WHEN 'japanese' THEN 'japanese'
 WHEN 'java' THEN 'java'
 WHEN 'javascript' THEN 'javascript'
 WHEN 'jenkins' THEN 'jenkins'
 WHEN 'jest' THEN 'jest'
 WHEN 'jira' THEN 'jira'
 WHEN 'jmeter' THEN 'jmeter'
 WHEN 'jquery' THEN 'jquery'
 WHEN 'js' THEN 'javascript'
 WHEN 'junit' THEN 'junit'
 WHEN 'jwt' THEN 'jwt'
 WHEN 'k8s' THEN 'kubernetes'
 WHEN 'kafka' THEN 'kafka'
 WHEN 'kotlin' THEN 'kotlin'
 WHEN 'kubernetes' THEN 'kubernetes'
 WHEN 'kế toán' THEN 'accounting'
 WHEN 'kỹ năng giao tiếp' THEN 'communication'
 WHEN 'kỹ năng làm việc nhóm' THEN 'teamwork'
 WHEN 'kỹ năng thuyết phục' THEN 'persuasion'
 WHEN 'kỹ năng thuyết trình' THEN 'presentation'
 WHEN 'kỹ năng đàm phán' THEN 'negotiation'
 WHEN 'langchain' THEN 'langchain'
 WHEN 'laravel' THEN 'laravel'
 WHEN 'large language models' THEN 'llm'
 WHEN 'linux' THEN 'linux'
 WHEN 'llm' THEN 'llm'
 WHEN 'làm việc nhóm' THEN 'teamwork'
 WHEN 'lập kế hoạch' THEN 'planning'
 WHEN 'machine learning' THEN 'machine-learning'
 WHEN 'macos' THEN 'macos'
 WHEN 'mariadb' THEN 'mariadb'
 WHEN 'matplotlib' THEN 'matplotlib'
 WHEN 'mes' THEN 'mes'
 WHEN 'microservices' THEN 'microservices'
 WHEN 'microsoft 365' THEN 'microsoft365'
 WHEN 'microsoft azure' THEN 'azure'
 WHEN 'microsoft excel' THEN 'excel'
 WHEN 'microsoft power bi' THEN 'powerbi'
 WHEN 'microsoft powerpoint' THEN 'powerpoint'
 WHEN 'microsoft sql server' THEN 'sqlserver'
 WHEN 'microsoft word' THEN 'word'
 WHEN 'mongodb' THEN 'mongodb'
 WHEN 'mssql' THEN 'sqlserver'
 WHEN 'mvc' THEN 'mvc'
 WHEN 'mysql' THEN 'mysql'
 WHEN 'nest.js' THEN 'nestjs'
 WHEN 'nestjs' THEN 'nestjs'
 WHEN 'next.js' THEN 'nextjs'
 WHEN 'nextjs' THEN 'nextjs'
 WHEN 'nginx' THEN 'nginx'
 WHEN 'node js' THEN 'nodejs'
 WHEN 'node.js' THEN 'nodejs'
 WHEN 'nodejs' THEN 'nodejs'
 WHEN 'nosql' THEN 'nosql'
 WHEN 'numpy' THEN 'numpy'
 WHEN 'oauth 2.0' THEN 'oauth2'
 WHEN 'oauth2' THEN 'oauth2'
 WHEN 'object oriented programming' THEN 'oop'
 WHEN 'odoo' THEN 'odoo'
 WHEN 'office 365' THEN 'microsoft365'
 WHEN 'oop' THEN 'oop'
 WHEN 'opensearch' THEN 'opensearch'
 WHEN 'oracle' THEN 'oracle'
 WHEN 'owasp top 10' THEN 'owasp-top10'
 WHEN 'pandas' THEN 'pandas'
 WHEN 'photoshop' THEN 'photoshop'
 WHEN 'php' THEN 'php'
 WHEN 'phân tích dữ liệu' THEN 'data-analysis'
 WHEN 'phân tích nghiệp vụ' THEN 'business-analysis'
 WHEN 'phân tích tài chính' THEN 'financial-analysis'
 WHEN 'playwright' THEN 'playwright'
 WHEN 'postgres' THEN 'postgresql'
 WHEN 'postgresql' THEN 'postgresql'
 WHEN 'postman' THEN 'postman'
 WHEN 'power automate' THEN 'power-automate'
 WHEN 'power bi' THEN 'powerbi'
 WHEN 'powerpoint' THEN 'powerpoint'
 WHEN 'powershell' THEN 'powershell'
 WHEN 'premiere' THEN 'premiere-pro'
 WHEN 'premiere pro' THEN 'premiere-pro'
 WHEN 'product management' THEN 'product-management'
 WHEN 'project management' THEN 'project-management'
 WHEN 'prometheus' THEN 'prometheus'
 WHEN 'pytest' THEN 'pytest'
 WHEN 'python' THEN 'python'
 WHEN 'pytorch' THEN 'pytorch'
 WHEN 'quản lý dự án' THEN 'project-management'
 WHEN 'quản trị mạng' THEN 'network-admin'
 WHEN 'rabbitmq' THEN 'rabbitmq'
 WHEN 'rag' THEN 'rag'
 WHEN 'rails' THEN 'rails'
 WHEN 'react' THEN 'react'
 WHEN 'react native' THEN 'react-native'
 WHEN 'react.js' THEN 'react'
 WHEN 'reactjs' THEN 'react'
 WHEN 'redis' THEN 'redis'
 WHEN 'rest api' THEN 'rest-api'
 WHEN 'restful api' THEN 'rest-api'
 WHEN 'retrieval augmented generation' THEN 'rag'
 WHEN 'revit' THEN 'revit'
 WHEN 'routing' THEN 'routing'
 WHEN 'ruby' THEN 'ruby'
 WHEN 'ruby on rails' THEN 'rails'
 WHEN 'rust' THEN 'rust'
 WHEN 'saas' THEN 'saas'
 WHEN 'sales' THEN 'sales'
 WHEN 'sales b2b' THEN 'b2b-sales'
 WHEN 'salesforce' THEN 'salesforce'
 WHEN 'sap' THEN 'sap'
 WHEN 'sap erp' THEN 'sap-erp'
 WHEN 'sass' THEN 'sass'
 WHEN 'scikit-learn' THEN 'scikit-learn'
 WHEN 'scrum' THEN 'scrum'
 WHEN 'scss' THEN 'sass'
 WHEN 'sdlc' THEN 'sdlc'
 WHEN 'selenium' THEN 'selenium'
 WHEN 'selenium webdriver' THEN 'selenium-webdriver'
 WHEN 'sem' THEN 'sem'
 WHEN 'seo' THEN 'seo'
 WHEN 'siem' THEN 'siem'
 WHEN 'sklearn' THEN 'scikit-learn'
 WHEN 'snowflake' THEN 'snowflake'
 WHEN 'solid' THEN 'solid'
 WHEN 'solidworks' THEN 'solidworks'
 WHEN 'spark' THEN 'spark'
 WHEN 'spring' THEN 'spring'
 WHEN 'spring boot' THEN 'spring-boot'
 WHEN 'spring security' THEN 'spring-security'
 WHEN 'springboot' THEN 'spring-boot'
 WHEN 'sql' THEN 'sql'
 WHEN 'sql server' THEN 'sqlserver'
 WHEN 'sqlite' THEN 'sqlite'
 WHEN 'srs' THEN 'srs'
 WHEN 'stlc' THEN 'stlc'
 WHEN 'swift' THEN 'swift'
 WHEN 'tableau' THEN 'tableau'
 WHEN 'tailwind css' THEN 'tailwind'
 WHEN 'tailwindcss' THEN 'tailwind'
 WHEN 'tcp/ip' THEN 'tcpip'
 WHEN 'tensorflow' THEN 'tensorflow'
 WHEN 'terraform' THEN 'terraform'
 WHEN 'thuyết phục' THEN 'persuasion'
 WHEN 'thuyết trình' THEN 'presentation'
 WHEN 'tin học văn phòng' THEN 'office-skills'
 WHEN 'tiếng anh' THEN 'english'
 WHEN 'tiếng nhật' THEN 'japanese'
 WHEN 'tiếng trung' THEN 'chinese'
 WHEN 'trello' THEN 'trello'
 WHEN 'ts' THEN 'typescript'
 WHEN 'typescript' THEN 'typescript'
 WHEN 'typography' THEN 'typography'
 WHEN 'uat' THEN 'uat'
 WHEN 'uml' THEN 'uml'
 WHEN 'unity' THEN 'unity'
 WHEN 'use case' THEN 'use-case'
 WHEN 'user story' THEN 'user-story'
 WHEN 'visio' THEN 'visio'
 WHEN 'vlan' THEN 'vlan'
 WHEN 'vue' THEN 'vue'
 WHEN 'vue.js' THEN 'vue'
 WHEN 'vuejs' THEN 'vue'
 WHEN 'websocket' THEN 'websocket'
 WHEN 'windows' THEN 'windows'
 WHEN 'windows server' THEN 'windows-server'
 WHEN 'wireframe' THEN 'wireframe'
 WHEN 'word' THEN 'word'
 WHEN 'đàm phán' THEN 'negotiation'
 END
$$;
CREATE OR REPLACE FUNCTION serving.normalize_skills(values_ text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT coalesce(array_agg(DISTINCT key ORDER BY key), '{}'::text[])
 FROM (SELECT serving.skill_key(v) key FROM unnest(values_) v) s WHERE key IS NOT NULL
$$;
CREATE OR REPLACE FUNCTION serving.preferred_skills(required_ text[], preferred_ text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$
 SELECT ARRAY(SELECT k FROM unnest(serving.normalize_skills(preferred_)) k
 WHERE NOT k=ANY(serving.normalize_skills(required_)) ORDER BY k)
$$;
CREATE OR REPLACE FUNCTION serving.skill_catalogue() RETURNS TABLE(key text,label text,aliases text[])
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path='' AS $$ VALUES
('3dsmax','3ds Max',ARRAY['3D Studio Max']::text[]),
('accounting','Kế toán',ARRAY[]::text[]),
('active-directory','Active Directory',ARRAY[]::text[]),
('after-effects','Adobe After Effects',ARRAY['After Effects']::text[]),
('agile','Agile',ARRAY[]::text[]),
('ai','AI',ARRAY['Artificial Intelligence']::text[]),
('airflow','Apache Airflow',ARRAY['Airflow']::text[]),
('android','Android',ARRAY[]::text[]),
('angular','Angular',ARRAY[]::text[]),
('ansible','Ansible',ARRAY[]::text[]),
('apache','Apache HTTP Server',ARRAY[]::text[]),
('api','API',ARRAY[]::text[]),
('api-testing','API testing',ARRAY[]::text[]),
('argocd','Argo CD',ARRAY['ArgoCD']::text[]),
('aspnet','ASP.NET',ARRAY[]::text[]),
('aspnet-core','ASP.NET Core',ARRAY[]::text[]),
('autocad','AutoCAD',ARRAY[]::text[]),
('aws','AWS',ARRAY['Amazon Web Services']::text[]),
('azure','Azure',ARRAY['Microsoft Azure']::text[]),
('azure-devops','Azure DevOps',ARRAY[]::text[]),
('b2b-sales','Sales B2B',ARRAY['B2B Sales']::text[]),
('bash','Bash',ARRAY[]::text[]),
('big-data','Big Data',ARRAY[]::text[]),
('bigquery','BigQuery',ARRAY[]::text[]),
('blender','Blender',ARRAY[]::text[]),
('bootstrap','Bootstrap',ARRAY[]::text[]),
('bpmn','BPMN',ARRAY[]::text[]),
('brd','BRD',ARRAY[]::text[]),
('business-analysis','Phân tích nghiệp vụ',ARRAY['Business Analysis']::text[]),
('c','C',ARRAY[]::text[]),
('canva','Canva',ARRAY[]::text[]),
('capcut','CapCut',ARRAY[]::text[]),
('chatgpt','ChatGPT',ARRAY[]::text[]),
('chinese','Tiếng Trung',ARRAY['Chinese']::text[]),
('cicd','CI/CD',ARRAY[]::text[]),
('claude','Claude',ARRAY[]::text[]),
('communication','Giao tiếp',ARRAY['Kỹ năng giao tiếp']::text[]),
('confluence','Confluence',ARRAY[]::text[]),
('content-marketing','Content Marketing',ARRAY[]::text[]),
('copywriting','Copywriting',ARRAY[]::text[]),
('cplusplus','C++',ARRAY['CPP']::text[]),
('crm','CRM',ARRAY[]::text[]),
('csharp','C#',ARRAY['CSharp']::text[]),
('css','CSS',ARRAY[]::text[]),
('css3','CSS3',ARRAY[]::text[]),
('customer-service','Chăm sóc khách hàng',ARRAY['CSKH']::text[]),
('cypress','Cypress',ARRAY[]::text[]),
('dart','Dart',ARRAY[]::text[]),
('data-analysis','Data Analysis',ARRAY['Phân tích dữ liệu']::text[]),
('data-modeling','Data modeling',ARRAY[]::text[]),
('data-warehouse','Data Warehouse',ARRAY[]::text[]),
('databricks','Databricks',ARRAY[]::text[]),
('dbt','dbt',ARRAY[]::text[]),
('design-patterns','Design Patterns',ARRAY[]::text[]),
('design-system','Design System',ARRAY[]::text[]),
('devops','DevOps',ARRAY[]::text[]),
('devsecops','DevSecOps',ARRAY[]::text[]),
('digital-marketing','Digital Marketing',ARRAY[]::text[]),
('django','Django',ARRAY[]::text[]),
('dns','DNS',ARRAY[]::text[]),
('docker','Docker',ARRAY[]::text[]),
('dotnet','.NET',ARRAY['Dotnet']::text[]),
('dotnet-core','.NET Core',ARRAY['Dotnet Core']::text[]),
('elasticsearch','Elasticsearch',ARRAY[]::text[]),
('english','Tiếng Anh',ARRAY['English']::text[]),
('erp','ERP',ARRAY[]::text[]),
('etl','ETL',ARRAY[]::text[]),
('excel','Excel',ARRAY['Microsoft Excel']::text[]),
('express','Express.js',ARRAY['ExpressJS','Express']::text[]),
('facebook-ads','Facebook Ads',ARRAY[]::text[]),
('fastapi','FastAPI',ARRAY[]::text[]),
('figma','Figma',ARRAY[]::text[]),
('financial-analysis','Phân tích tài chính',ARRAY['Financial Analysis']::text[]),
('firebase','Firebase',ARRAY[]::text[]),
('flask','Flask',ARRAY[]::text[]),
('flutter','Flutter',ARRAY[]::text[]),
('gcp','GCP',ARRAY['Google Cloud Platform']::text[]),
('git','Git',ARRAY[]::text[]),
('github','GitHub',ARRAY[]::text[]),
('github-actions','GitHub Actions',ARRAY[]::text[]),
('gitlab','GitLab',ARRAY[]::text[]),
('gitlab-ci','GitLab CI',ARRAY[]::text[]),
('go','Go',ARRAY['Golang']::text[]),
('google-ads','Google Ads',ARRAY[]::text[]),
('google-analytics','Google Analytics',ARRAY[]::text[]),
('google-sheets','Google Sheets',ARRAY[]::text[]),
('grafana','Grafana',ARRAY[]::text[]),
('graphql','GraphQL',ARRAY[]::text[]),
('grpc','gRPC',ARRAY[]::text[]),
('hadoop','Hadoop',ARRAY[]::text[]),
('helm','Helm',ARRAY[]::text[]),
('hive','Hive',ARRAY[]::text[]),
('hrm','HRM',ARRAY[]::text[]),
('html','HTML',ARRAY[]::text[]),
('html5','HTML5',ARRAY[]::text[]),
('illustrator','Adobe Illustrator',ARRAY['Illustrator']::text[]),
('indesign','Adobe InDesign',ARRAY['InDesign']::text[]),
('ios','iOS',ARRAY[]::text[]),
('iso27001','ISO 27001',ARRAY['ISO27001']::text[]),
('japanese','Tiếng Nhật',ARRAY['Japanese']::text[]),
('java','Java',ARRAY[]::text[]),
('javascript','JavaScript',ARRAY['JS']::text[]),
('jenkins','Jenkins',ARRAY[]::text[]),
('jest','Jest',ARRAY[]::text[]),
('jira','Jira',ARRAY[]::text[]),
('jmeter','JMeter',ARRAY[]::text[]),
('jquery','jQuery',ARRAY[]::text[]),
('junit','JUnit',ARRAY[]::text[]),
('jwt','JWT',ARRAY[]::text[]),
('kafka','Kafka',ARRAY['Apache Kafka']::text[]),
('kotlin','Kotlin',ARRAY[]::text[]),
('kubernetes','Kubernetes',ARRAY['K8s']::text[]),
('langchain','LangChain',ARRAY[]::text[]),
('laravel','Laravel',ARRAY[]::text[]),
('linux','Linux',ARRAY[]::text[]),
('llm','LLM',ARRAY['Large Language Models']::text[]),
('machine-learning','Machine Learning',ARRAY[]::text[]),
('macos','macOS',ARRAY[]::text[]),
('mariadb','MariaDB',ARRAY[]::text[]),
('matplotlib','Matplotlib',ARRAY[]::text[]),
('mes','MES',ARRAY[]::text[]),
('microservices','Microservices',ARRAY[]::text[]),
('microsoft365','Microsoft 365',ARRAY['Office 365']::text[]),
('mongodb','MongoDB',ARRAY[]::text[]),
('mvc','MVC',ARRAY[]::text[]),
('mysql','MySQL',ARRAY[]::text[]),
('negotiation','Đàm phán',ARRAY['Kỹ năng đàm phán']::text[]),
('nestjs','NestJS',ARRAY['Nest.js']::text[]),
('network-admin','Quản trị mạng',ARRAY[]::text[]),
('nextjs','Next.js',ARRAY['NextJS']::text[]),
('nginx','Nginx',ARRAY[]::text[]),
('nodejs','Node.js',ARRAY['NodeJS','Node JS']::text[]),
('nosql','NoSQL',ARRAY[]::text[]),
('numpy','NumPy',ARRAY[]::text[]),
('oauth2','OAuth2',ARRAY['OAuth 2.0']::text[]),
('odoo','Odoo',ARRAY[]::text[]),
('office-skills','Tin học văn phòng',ARRAY[]::text[]),
('oop','OOP',ARRAY['Object Oriented Programming']::text[]),
('opensearch','OpenSearch',ARRAY[]::text[]),
('oracle','Oracle',ARRAY[]::text[]),
('owasp-top10','OWASP Top 10',ARRAY[]::text[]),
('pandas','Pandas',ARRAY[]::text[]),
('persuasion','Thuyết phục',ARRAY['Kỹ năng thuyết phục']::text[]),
('photoshop','Adobe Photoshop',ARRAY['Photoshop']::text[]),
('php','PHP',ARRAY[]::text[]),
('planning','Lập kế hoạch',ARRAY[]::text[]),
('playwright','Playwright',ARRAY[]::text[]),
('postgresql','PostgreSQL',ARRAY['Postgres']::text[]),
('postman','Postman',ARRAY[]::text[]),
('power-automate','Power Automate',ARRAY[]::text[]),
('powerbi','Power BI',ARRAY['Microsoft Power BI']::text[]),
('powerpoint','PowerPoint',ARRAY['Microsoft PowerPoint']::text[]),
('powershell','PowerShell',ARRAY[]::text[]),
('premiere-pro','Adobe Premiere Pro',ARRAY['Premiere Pro','Premiere']::text[]),
('presentation','Thuyết trình',ARRAY['Kỹ năng thuyết trình']::text[]),
('product-management','Product Management',ARRAY[]::text[]),
('project-management','Quản lý dự án',ARRAY['Project Management']::text[]),
('prometheus','Prometheus',ARRAY[]::text[]),
('pytest','pytest',ARRAY[]::text[]),
('python','Python',ARRAY[]::text[]),
('pytorch','PyTorch',ARRAY[]::text[]),
('rabbitmq','RabbitMQ',ARRAY[]::text[]),
('rag','RAG',ARRAY['Retrieval Augmented Generation']::text[]),
('rails','Ruby on Rails',ARRAY['Rails']::text[]),
('react','React',ARRAY['ReactJS','React.js']::text[]),
('react-native','React Native',ARRAY[]::text[]),
('redis','Redis',ARRAY[]::text[]),
('rest-api','REST API',ARRAY['RESTful API']::text[]),
('revit','Revit',ARRAY[]::text[]),
('routing','Routing',ARRAY[]::text[]),
('ruby','Ruby',ARRAY[]::text[]),
('rust','Rust',ARRAY[]::text[]),
('saas','SaaS',ARRAY[]::text[]),
('sales','Sales',ARRAY['Bán hàng']::text[]),
('salesforce','Salesforce',ARRAY[]::text[]),
('sap','SAP',ARRAY[]::text[]),
('sap-erp','SAP ERP',ARRAY[]::text[]),
('sass','Sass',ARRAY['SCSS']::text[]),
('scikit-learn','scikit-learn',ARRAY['sklearn']::text[]),
('scrum','Scrum',ARRAY[]::text[]),
('sdlc','SDLC',ARRAY[]::text[]),
('selenium','Selenium',ARRAY[]::text[]),
('selenium-webdriver','Selenium WebDriver',ARRAY[]::text[]),
('sem','SEM',ARRAY[]::text[]),
('seo','SEO',ARRAY[]::text[]),
('siem','SIEM',ARRAY[]::text[]),
('snowflake','Snowflake',ARRAY[]::text[]),
('solid','SOLID',ARRAY[]::text[]),
('solidworks','SolidWorks',ARRAY[]::text[]),
('spark','Apache Spark',ARRAY['Spark']::text[]),
('spring','Spring',ARRAY[]::text[]),
('spring-boot','Spring Boot',ARRAY['SpringBoot']::text[]),
('spring-security','Spring Security',ARRAY[]::text[]),
('sql','SQL',ARRAY[]::text[]),
('sqlite','SQLite',ARRAY[]::text[]),
('sqlserver','SQL Server',ARRAY['Microsoft SQL Server','MSSQL']::text[]),
('srs','SRS',ARRAY[]::text[]),
('stlc','STLC',ARRAY[]::text[]),
('swift','Swift',ARRAY[]::text[]),
('tableau','Tableau',ARRAY[]::text[]),
('tailwind','Tailwind CSS',ARRAY['TailwindCSS']::text[]),
('tcpip','TCP/IP',ARRAY[]::text[]),
('teamwork','Làm việc nhóm',ARRAY['Kỹ năng làm việc nhóm']::text[]),
('tensorflow','TensorFlow',ARRAY[]::text[]),
('terraform','Terraform',ARRAY[]::text[]),
('trello','Trello',ARRAY[]::text[]),
('typescript','TypeScript',ARRAY['TS']::text[]),
('typography','Typography',ARRAY[]::text[]),
('uat','UAT',ARRAY[]::text[]),
('uml','UML',ARRAY[]::text[]),
('unity','Unity',ARRAY[]::text[]),
('use-case','Use case',ARRAY[]::text[]),
('user-story','User Story',ARRAY[]::text[]),
('visio','Visio',ARRAY[]::text[]),
('vlan','VLAN',ARRAY[]::text[]),
('vue','Vue.js',ARRAY['VueJS','Vue']::text[]),
('websocket','WebSocket',ARRAY[]::text[]),
('windows','Windows',ARRAY[]::text[]),
('windows-server','Windows Server',ARRAY[]::text[]),
('wireframe','Wireframe',ARRAY[]::text[]),
('word','Word',ARRAY['Microsoft Word']::text[])
$$;
ALTER TABLE serving.jobs
 ADD COLUMN IF NOT EXISTS required_skill_keys text[] GENERATED ALWAYS AS
 (CASE WHEN enrichment_status='succeeded' THEN serving.normalize_skills(skills_required) ELSE '{}'::text[] END) STORED,
 ADD COLUMN IF NOT EXISTS preferred_skill_keys text[] GENERATED ALWAYS AS
 (CASE WHEN enrichment_status='succeeded' THEN serving.preferred_skills(skills_required,skills_preferred) ELSE '{}'::text[] END) STORED;
CREATE INDEX IF NOT EXISTS jobs_required_skills_idx ON serving.jobs USING gin(required_skill_keys);
CREATE INDEX IF NOT EXISTS jobs_all_skills_idx ON serving.jobs USING gin((required_skill_keys || preferred_skill_keys));
CREATE OR REPLACE FUNCTION serving.skills_search_query(p_query text) RETURNS tsquery LANGUAGE plpgsql STABLE SET search_path='' AS $$
DECLARE
 q tsquery; normalized text; tail text; head text; terms text[];
 term_query tsquery; tail_query tsquery; term_index integer;
BEGIN
 IF btrim(COALESCE(p_query,'')) <> '' THEN
   q := websearch_to_tsquery('pg_catalog.simple', serving.normalize_search(p_query));
   IF numnode(q) = 0 THEN RETURN q; END IF;
   normalized := regexp_replace(serving.normalize_search(p_query), '[[:space:]]+$', '');
   -- Preserve web-search syntax, including lowercase OR. An internal hyphen
   -- belongs to a technology name, not to the exclusion operator.
   IF normalized !~ '"'
      AND normalized !~ '(^|[^[:alnum:]_-])or($|[^[:alnum:]_-])'
      AND normalized !~ '(^|[^[:alnum:]_])-'
   THEN
     tail := substring(normalized FROM '[^[:space:]]+$');
     head := left(normalized, length(normalized) - length(tail));
     -- Let PostgreSQL tokenize aliases, punctuation, hosts and Unicode.
     -- For a final hyphenated word use its parts: the full compound would
     -- otherwise require the unfinished spelling to match exactly.
     SELECT array_agg(l.lexeme ORDER BY d.ordinality, l.ordinality)
       INTO terms
       FROM ts_debug('pg_catalog.simple', tail) WITH ORDINALITY AS d
       CROSS JOIN LATERAL unnest(d.lexemes) WITH ORDINALITY AS l(lexeme, ordinality)
       WHERE d.alias NOT IN ('asciihword', 'numhword', 'hword');
     IF length(terms[array_length(terms, 1)]) >= 3 THEN
       FOR term_index IN 1..array_length(terms, 1) LOOP
         -- tsvector output quotes/escapes an already normalized lexeme.
         -- No raw input is interpreted as tsquery syntax or dynamic SQL.
         term_query := (array_to_tsvector(ARRAY[terms[term_index]])::text ||
           CASE WHEN term_index = array_length(terms, 1) THEN ':*' ELSE '' END)::tsquery;
         tail_query := CASE WHEN tail_query IS NULL THEN term_query
                            ELSE tail_query && term_query END;
       END LOOP;
       q := websearch_to_tsquery('pg_catalog.simple', head);
       q := CASE WHEN numnode(q) = 0 THEN tail_query ELSE q && tail_query END;
     END IF;
   END IF;
 END IF;

 RETURN q;
END $$;
CREATE OR REPLACE FUNCTION serving.validate_skill_filters(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required') RETURNS void LANGUAGE plpgsql STABLE SET search_path='' AS $$ BEGIN
 IF length(coalesce(p_query,''))>200 OR p_days IS NULL OR p_days NOT IN (0,1,7,30)

 OR p_experience IS NULL OR p_experience NOT IN ('','zero','under1','1to3','3to5','5plus','unknown')
 OR p_sources IS NULL OR p_cities IS NULL OR p_seniority IS NULL OR p_modes IS NULL
 OR cardinality(p_sources)>20 OR cardinality(p_cities)>20 OR cardinality(p_seniority)>9 OR cardinality(p_modes)>4
 OR EXISTS(SELECT 1 FROM unnest(p_sources) x WHERE x IS NULL OR x !~ '^[a-z0-9_-]{1,50}$')
 OR EXISTS(SELECT 1 FROM unnest(p_cities) x WHERE x IS NULL OR length(x) NOT BETWEEN 1 AND 120 OR x ~ '[[:cntrl:]]')
 OR EXISTS(SELECT 1 FROM unnest(p_seniority) x WHERE x IS NULL OR x NOT IN ('intern','fresher','junior','middle','senior','lead','manager','director','unknown'))
 OR EXISTS(SELECT 1 FROM unnest(p_modes) x WHERE x IS NULL OR x NOT IN ('onsite','hybrid','remote','unknown'))
 OR p_skills IS NULL OR cardinality(p_skills)>10 OR p_skill_match IS NULL OR p_skill_match NOT IN ('any','all')
 OR p_skill_scope IS NULL OR p_skill_scope NOT IN ('required','all')
 OR EXISTS(SELECT 1 FROM unnest(p_skills) k WHERE k IS NULL OR NOT EXISTS(SELECT 1 FROM serving.skill_catalogue() c WHERE c.key=k))
 THEN RAISE EXCEPTION 'Invalid search filters' USING ERRCODE='22023'; END IF;
 END $$;
CREATE OR REPLACE FUNCTION serving.matching_skill_ids(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required') RETURNS TABLE(id bigint) LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $$
 WITH search AS MATERIALIZED (SELECT serving.skills_search_query(p_query) q) SELECT j.id FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
 CROSS JOIN search sq
 CROSS JOIN LATERAL (SELECT
   CASE WHEN j.enrichment_status='succeeded' AND j.experience_min_years BETWEEN 0 AND 60
     AND (j.experience_max_years IS NULL OR (j.experience_max_years BETWEEN j.experience_min_years AND 60))
     THEN j.experience_min_years END AS exp,
   CASE WHEN j.enrichment_status='succeeded' THEN
     ARRAY(SELECT x FROM unnest(j.seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END AS levels,
   CASE WHEN j.enrichment_status='succeeded' AND j.work_mode IN ('onsite','hybrid','remote') THEN j.work_mode END AS mode
 ) e
 WHERE (sq.q IS NULL OR j.search_vector @@ sq.q)
 AND (cardinality(p_sources)=0 OR s.code=ANY(p_sources))
 AND (cardinality(p_cities)=0 OR j.location_cities && p_cities)
 AND (p_experience='' OR (p_experience='unknown' AND e.exp IS NULL)
   OR (p_experience='zero' AND e.exp=0) OR (p_experience='under1' AND e.exp>0 AND e.exp<1)
   OR (p_experience='1to3' AND e.exp>=1 AND e.exp<3) OR (p_experience='3to5' AND e.exp>=3 AND e.exp<5)
   OR (p_experience='5plus' AND e.exp>=5))
 AND (cardinality(p_seniority)=0 OR e.levels && p_seniority OR ('unknown'=ANY(p_seniority) AND cardinality(e.levels)=0))
 AND (cardinality(p_modes)=0 OR e.mode=ANY(p_modes) OR ('unknown'=ANY(p_modes) AND e.mode IS NULL))
 AND (p_days=0 OR coalesce(j.posted_at,j.first_seen_at) BETWEEN CURRENT_TIMESTAMP - make_interval(days=>p_days) AND CURRENT_TIMESTAMP)
 AND (cardinality(p_skills)=0 OR CASE WHEN p_skill_match='all'
 THEN (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) @> p_skills
 ELSE (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) && p_skills END)
$$;
CREATE OR REPLACE FUNCTION serving.search_jobs_v3(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required', p_sort text DEFAULT 'relevance', p_limit integer DEFAULT 20, p_offset integer DEFAULT 0)
RETURNS TABLE (
 id bigint,title text,employer_name_raw text,canonical_url text,
 source_code text,source_name text,location_cities text[],salary_raw text,
 employment_type_raw text,experience_raw text,posted_at timestamptz,last_seen_at timestamptz,
 first_seen_at timestamptz,experience_min_years double precision,experience_max_years double precision,
 seniority_levels text[],work_mode text,employment_type text,enrichment_status text,required_skill_keys text[],preferred_skill_keys text[],score real
)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$ DECLARE query_ tsquery; BEGIN
 PERFORM serving.validate_skill_filters(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope);
 IF p_sort IS NULL OR p_sort NOT IN ('relevance','newest') OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 10000 THEN
 RAISE EXCEPTION 'Invalid search pagination' USING ERRCODE='22023'; END IF;
 query_ := serving.skills_search_query(p_query);
 RETURN QUERY SELECT j.id,j.title,j.employer_name_raw,j.canonical_url,s.code,s.display_name,j.location_cities,
 j.salary_raw,j.employment_type_raw,j.experience_raw,j.posted_at,j.last_seen_at,j.first_seen_at,
 j.experience_min_years,j.experience_max_years,j.seniority_levels,j.work_mode,j.employment_type,j.enrichment_status,
 j.required_skill_keys,j.preferred_skill_keys,
 coalesce(ts_rank(j.search_vector,query_),0::real) score
 FROM serving.jobs j JOIN serving.sources s ON s.id=j.source_id
  CROSS JOIN LATERAL (SELECT
   CASE WHEN j.enrichment_status='succeeded' AND j.experience_min_years BETWEEN 0 AND 60
     AND (j.experience_max_years IS NULL OR (j.experience_max_years BETWEEN j.experience_min_years AND 60))
     THEN j.experience_min_years END AS exp,
   CASE WHEN j.enrichment_status='succeeded' THEN
     ARRAY(SELECT x FROM unnest(j.seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END AS levels,
   CASE WHEN j.enrichment_status='succeeded' AND j.work_mode IN ('onsite','hybrid','remote') THEN j.work_mode END AS mode
 ) e
 WHERE (query_ IS NULL OR j.search_vector @@ query_)
 AND (cardinality(p_sources)=0 OR s.code=ANY(p_sources))
 AND (cardinality(p_cities)=0 OR j.location_cities && p_cities)
 AND (p_experience='' OR (p_experience='unknown' AND e.exp IS NULL)
   OR (p_experience='zero' AND e.exp=0) OR (p_experience='under1' AND e.exp>0 AND e.exp<1)
   OR (p_experience='1to3' AND e.exp>=1 AND e.exp<3) OR (p_experience='3to5' AND e.exp>=3 AND e.exp<5)
   OR (p_experience='5plus' AND e.exp>=5))
 AND (cardinality(p_seniority)=0 OR e.levels && p_seniority OR ('unknown'=ANY(p_seniority) AND cardinality(e.levels)=0))
 AND (cardinality(p_modes)=0 OR e.mode=ANY(p_modes) OR ('unknown'=ANY(p_modes) AND e.mode IS NULL))
 AND (p_days=0 OR coalesce(j.posted_at,j.first_seen_at) BETWEEN CURRENT_TIMESTAMP - make_interval(days=>p_days) AND CURRENT_TIMESTAMP)
 AND (cardinality(p_skills)=0 OR CASE WHEN p_skill_match='all'
 THEN (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) @> p_skills
 ELSE (CASE WHEN p_skill_scope='all' THEN j.required_skill_keys || j.preferred_skill_keys ELSE j.required_skill_keys END) && p_skills END)

 ORDER BY CASE WHEN p_sort='relevance' THEN coalesce(ts_rank(j.search_vector,query_),0::real) END DESC,
 coalesce(j.posted_at,j.first_seen_at) DESC NULLS LAST,j.id DESC LIMIT p_limit OFFSET p_offset;
END $$;
CREATE OR REPLACE FUNCTION serving.job_statistics_v1(p_query text DEFAULT '', p_sources text[] DEFAULT '{}', p_cities text[] DEFAULT '{}', p_experience text DEFAULT '', p_seniority text[] DEFAULT '{}', p_modes text[] DEFAULT '{}', p_days integer DEFAULT 0, p_skills text[] DEFAULT '{}', p_skill_match text DEFAULT 'any', p_skill_scope text DEFAULT 'required') RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $$
DECLARE result jsonb; BEGIN
 PERFORM serving.validate_skill_filters(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope);
 WITH base AS MATERIALIZED (
 SELECT j.id,source_id,location_cities,enrichment_status,skills_required,skills_preferred,required_skill_keys,preferred_skill_keys,
 CASE WHEN enrichment_status='succeeded' AND experience_min_years BETWEEN 0 AND 60 AND (experience_max_years IS NULL OR experience_max_years BETWEEN experience_min_years AND 60) THEN experience_min_years END exp,
 CASE WHEN enrichment_status='succeeded' THEN ARRAY(SELECT DISTINCT x FROM unnest(seniority_levels) x WHERE x IN ('intern','fresher','junior','middle','senior','lead','manager','director')) ELSE '{}'::text[] END levels,
 CASE WHEN enrichment_status='succeeded' AND work_mode IN ('onsite','hybrid','remote') THEN work_mode END mode
 FROM serving.matching_skill_ids(p_query,p_sources,p_cities,p_experience,p_seniority,p_modes,p_days,p_skills,p_skill_match,p_skill_scope) matches JOIN serving.jobs j ON j.id=matches.id
 ), facts AS (
 SELECT 'source'::text kind,s.code key,s.display_name label,b.id FROM base b JOIN serving.sources s ON s.id=b.source_id
 UNION ALL SELECT 'city',c,c,b.id FROM base b LEFT JOIN LATERAL (SELECT DISTINCT x c FROM unnest(b.location_cities) x WHERE nullif(btrim(x),'') IS NOT NULL) loc ON true
 UNION ALL SELECT 'skill',c.key,c.label,b.id FROM base b CROSS JOIN LATERAL unnest(CASE WHEN p_skill_scope='all' THEN required_skill_keys || preferred_skill_keys ELSE required_skill_keys END) k JOIN serving.skill_catalogue() c ON c.key=k
 UNION ALL SELECT 'seniority',coalesce(l,'unknown'),coalesce(l,'unknown'),b.id FROM base b LEFT JOIN LATERAL unnest(levels) l ON true
 UNION ALL SELECT 'mode',coalesce(mode,'unknown'),coalesce(mode,'unknown'),id FROM base
 UNION ALL SELECT 'experience',bucket,bucket,id FROM (SELECT id,CASE WHEN exp IS NULL THEN 'unknown' WHEN exp=0 THEN 'zero' WHEN exp<1 THEN 'under1' WHEN exp<3 THEN '1to3' WHEN exp<5 THEN '3to5' ELSE '5plus' END bucket FROM base) e
 ), counts AS (SELECT kind,key,label,count(DISTINCT id)::int count FROM facts GROUP BY kind,key,label), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY kind ORDER BY count DESC,label NULLS LAST) pos FROM counts
 ) SELECT jsonb_build_object('total',(SELECT count(*) FROM base),'calculatedAt',CURRENT_TIMESTAMP,
 'rows',coalesce((SELECT jsonb_agg(jsonb_build_object('kind',kind,'key',key,'label',label,'count',count) ORDER BY kind,pos) FROM ranked WHERE kind<>'skill' OR pos<=15),'[]'::jsonb),
 'coverage',(SELECT jsonb_build_object('enriched',count(*) FILTER(WHERE enrichment_status='succeeded'),
 'extracted',count(*) FILTER(WHERE enrichment_status='succeeded' AND (cardinality(skills_required)>0 OR (p_skill_scope='all' AND cardinality(skills_preferred)>0))),
 'normalized',count(*) FILTER(WHERE cardinality(required_skill_keys)>0 OR (p_skill_scope='all' AND cardinality(preferred_skill_keys)>0)),
 'experience',count(exp),'seniority',count(*) FILTER(WHERE cardinality(levels)>0),'mode',count(mode)) FROM base)) INTO result;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION serving.skill_key(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.normalize_skills(text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.preferred_skills(text[],text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.skill_catalogue() FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.skills_search_query(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.validate_skill_filters(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.matching_skill_ids(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.search_jobs_v3(text,text[],text[],text,text[],text[],integer,text[],text,text,text,integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION serving.job_statistics_v1(text,text[],text[],text,text[],text[],integer,text[],text,text) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='joblake_web_reader') THEN
GRANT EXECUTE ON FUNCTION serving.skill_key(text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.normalize_skills(text[]) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.preferred_skills(text[],text[]) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.skill_catalogue() TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.skills_search_query(text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.validate_skill_filters(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.matching_skill_ids(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.search_jobs_v3(text,text[],text[],text,text[],text[],integer,text[],text,text,text,integer,integer) TO joblake_web_reader;
GRANT EXECUTE ON FUNCTION serving.job_statistics_v1(text,text[],text[],text,text[],text[],integer,text[],text,text) TO joblake_web_reader;
END IF; END $$;
