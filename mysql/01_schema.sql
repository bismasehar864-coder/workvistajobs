-- MySQL dump 10.13  Distrib 26.7.0, for macos26.6 (arm64)
--
-- Host: localhost    Database: workvista_db
-- ------------------------------------------------------
-- Server version	26.7.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `auth_group`
--

DROP TABLE IF EXISTS `auth_group`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_group_permissions`
--

DROP TABLE IF EXISTS `auth_group_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_group_permissions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `group_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_permission`
--

DROP TABLE IF EXISTS `auth_permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_permission` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `content_type_id` int NOT NULL,
  `codename` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=69 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user`
--

DROP TABLE IF EXISTS `auth_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `password` varchar(128) NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) NOT NULL,
  `first_name` varchar(150) NOT NULL,
  `last_name` varchar(150) NOT NULL,
  `email` varchar(254) NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=33 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user_groups`
--

DROP TABLE IF EXISTS `auth_user_groups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user_groups` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `group_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_groups_user_id_group_id_94350c0c_uniq` (`user_id`,`group_id`),
  KEY `auth_user_groups_group_id_97559544_fk_auth_group_id` (`group_id`),
  CONSTRAINT `auth_user_groups_group_id_97559544_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
  CONSTRAINT `auth_user_groups_user_id_6a12ed8b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `auth_user_user_permissions`
--

DROP TABLE IF EXISTS `auth_user_user_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `auth_user_user_permissions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `permission_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq` (`user_id`,`permission_id`),
  KEY `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_admin_log`
--

DROP TABLE IF EXISTS `django_admin_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_admin_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `action_time` datetime(6) NOT NULL,
  `object_id` longtext,
  `object_repr` varchar(200) NOT NULL,
  `action_flag` smallint unsigned NOT NULL,
  `change_message` longtext NOT NULL,
  `content_type_id` int DEFAULT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `django_admin_log_content_type_id_c4bce8eb_fk_django_co` (`content_type_id`),
  KEY `django_admin_log_user_id_c564eba6_fk_auth_user_id` (`user_id`),
  CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`),
  CONSTRAINT `django_admin_log_user_id_c564eba6_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `django_admin_log_chk_1` CHECK ((`action_flag` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_content_type`
--

DROP TABLE IF EXISTS `django_content_type`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_content_type` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) NOT NULL,
  `model` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_migrations`
--

DROP TABLE IF EXISTS `django_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_migrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `app` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=41 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `django_session`
--

DROP TABLE IF EXISTS `django_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `django_session` (
  `session_key` varchar(40) NOT NULL,
  `session_data` longtext NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_company`
--

DROP TABLE IF EXISTS `jobs_company`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_company` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `location` varchar(255) NOT NULL,
  `website` varchar(500) NOT NULL,
  `description` longtext NOT NULL,
  `founded_year` smallint unsigned DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `owner_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `owner_id` (`owner_id`),
  CONSTRAINT `jobs_company_owner_id_20ecf99e_fk_auth_user_id` FOREIGN KEY (`owner_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `jobs_company_chk_1` CHECK ((`founded_year` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_companybranch`
--

DROP TABLE IF EXISTS `jobs_companybranch`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_companybranch` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `location` varchar(255) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `company_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `jobs_companybranch_company_id_name_3a984c82_uniq` (`company_id`,`name`),
  CONSTRAINT `jobs_companybranch_company_id_d7e47d49_fk_jobs_company_id` FOREIGN KEY (`company_id`) REFERENCES `jobs_company` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_cvdata`
--

DROP TABLE IF EXISTS `jobs_cvdata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_cvdata` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) DEFAULT NULL,
  `email` varchar(254) DEFAULT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `skills` json DEFAULT NULL,
  `education` json DEFAULT NULL,
  `experience` json DEFAULT NULL,
  `user_id` int NOT NULL,
  `certifications` json DEFAULT NULL,
  `honours` json DEFAULT NULL,
  `languages` json DEFAULT NULL,
  `training` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`),
  CONSTRAINT `jobs_cvdata_user_id_b1e1bee6_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_job`
--

DROP TABLE IF EXISTS `jobs_job`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_job` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `title` varchar(255) NOT NULL,
  `company` varchar(255) NOT NULL,
  `location` varchar(255) NOT NULL,
  `salary` varchar(255) NOT NULL,
  `experience` varchar(255) NOT NULL,
  `education` longtext NOT NULL,
  `skills` json NOT NULL,
  `posted` varchar(100) NOT NULL,
  `job_link` varchar(1000) NOT NULL,
  `source` varchar(50) NOT NULL,
  `description` longtext NOT NULL,
  `scraped_at` datetime(6) NOT NULL,
  `job_type` varchar(100) NOT NULL,
  `first_seen_at` datetime(6) NOT NULL,
  `category` varchar(30) NOT NULL,
  `posted_by_id` int DEFAULT NULL,
  `salary_max` int unsigned DEFAULT NULL,
  `salary_min` int unsigned DEFAULT NULL,
  `branch_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `jobs_job_category_b575d8c5` (`category`),
  KEY `jobs_job_posted_by_id_9b3eb7ca_fk_auth_user_id` (`posted_by_id`),
  KEY `jobs_job_branch_id_2643c385_fk_jobs_companybranch_id` (`branch_id`),
  CONSTRAINT `jobs_job_branch_id_2643c385_fk_jobs_companybranch_id` FOREIGN KEY (`branch_id`) REFERENCES `jobs_companybranch` (`id`),
  CONSTRAINT `jobs_job_posted_by_id_9b3eb7ca_fk_auth_user_id` FOREIGN KEY (`posted_by_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `jobs_job_chk_1` CHECK ((`salary_max` >= 0)),
  CONSTRAINT `jobs_job_chk_2` CHECK ((`salary_min` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=249 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_notification`
--

DROP TABLE IF EXISTS `jobs_notification`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_notification` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `kind` varchar(30) NOT NULL,
  `title` varchar(255) NOT NULL,
  `body` varchar(500) NOT NULL,
  `score` smallint unsigned NOT NULL,
  `read_at` datetime(6) DEFAULT NULL,
  `emailed_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `job_id` bigint DEFAULT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `jobs_notification_user_id_job_id_kind_e3d4aef8_uniq` (`user_id`,`job_id`,`kind`),
  KEY `jobs_notification_job_id_f4d84073_fk_jobs_job_id` (`job_id`),
  KEY `jobs_notification_kind_787c8015` (`kind`),
  KEY `jobs_notification_created_at_3f336cf6` (`created_at`),
  KEY `jobs_notifi_user_id_402ea2_idx` (`user_id`,`read_at`),
  CONSTRAINT `jobs_notification_job_id_f4d84073_fk_jobs_job_id` FOREIGN KEY (`job_id`) REFERENCES `jobs_job` (`id`),
  CONSTRAINT `jobs_notification_user_id_bd18f659_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`),
  CONSTRAINT `jobs_notification_chk_1` CHECK ((`score` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_profile`
--

DROP TABLE IF EXISTS `jobs_profile`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_profile` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `role` varchar(20) NOT NULL,
  `user_id` int NOT NULL,
  `cv` varchar(100) DEFAULT NULL,
  `skills` json DEFAULT NULL,
  `job_title` varchar(100) DEFAULT NULL,
  `job_type` json NOT NULL,
  `location` varchar(100) DEFAULT NULL,
  `salary` int DEFAULT NULL,
  `alerts_checked_at` datetime(6) DEFAULT NULL,
  `email_job_alerts` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`),
  CONSTRAINT `jobs_profile_user_id_effa5004_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=33 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_savedjob`
--

DROP TABLE IF EXISTS `jobs_savedjob`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_savedjob` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `saved_at` datetime(6) NOT NULL,
  `job_id` bigint NOT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `jobs_savedjob_user_id_job_id_2d68af5b_uniq` (`user_id`,`job_id`),
  KEY `jobs_savedjob_job_id_e069c6bf_fk_jobs_job_id` (`job_id`),
  CONSTRAINT `jobs_savedjob_job_id_e069c6bf_fk_jobs_job_id` FOREIGN KEY (`job_id`) REFERENCES `jobs_job` (`id`),
  CONSTRAINT `jobs_savedjob_user_id_49e68f73_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_scrapelock`
--

DROP TABLE IF EXISTS `jobs_scrapelock`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_scrapelock` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `key` varchar(50) NOT NULL,
  `locked_until` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_scraperun`
--

DROP TABLE IF EXISTS `jobs_scraperun`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_scraperun` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `source` varchar(50) NOT NULL,
  `status` varchar(10) NOT NULL,
  `started_at` datetime(6) NOT NULL,
  `finished_at` datetime(6) DEFAULT NULL,
  `jobs_saved` int unsigned NOT NULL,
  `message` longtext NOT NULL,
  PRIMARY KEY (`id`),
  KEY `jobs_scrape_source_083676_idx` (`source`,`started_at` DESC),
  CONSTRAINT `jobs_scraperun_chk_1` CHECK ((`jobs_saved` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=62 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_scraperwebsite`
--

DROP TABLE IF EXISTS `jobs_scraperwebsite`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_scraperwebsite` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `url` varchar(200) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `jobs_useractivity`
--

DROP TABLE IF EXISTS `jobs_useractivity`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `jobs_useractivity` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `activity_type` varchar(10) NOT NULL,
  `category` varchar(30) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `job_id` bigint DEFAULT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `jobs_useractivity_job_id_4d2432db_fk_jobs_job_id` (`job_id`),
  KEY `jobs_userac_user_id_30c046_idx` (`user_id`,`created_at`),
  CONSTRAINT `jobs_useractivity_job_id_4d2432db_fk_jobs_job_id` FOREIGN KEY (`job_id`) REFERENCES `jobs_job` (`id`),
  CONSTRAINT `jobs_useractivity_user_id_afc8f690_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=151 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-14  2:07:41
-- MySQL dump 10.13  Distrib 26.7.0, for macos26.6 (arm64)
--
-- Host: localhost    Database: workvista_db
-- ------------------------------------------------------
-- Server version	26.7.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Dumping data for table `django_migrations`
--

LOCK TABLES `django_migrations` WRITE;
/*!40000 ALTER TABLE `django_migrations` DISABLE KEYS */;
INSERT INTO `django_migrations` (`id`, `app`, `name`, `applied`) VALUES (1,'contenttypes','0001_initial','2026-09-11 17:54:19.162752'),(2,'auth','0001_initial','2026-09-11 17:54:19.245833'),(3,'admin','0001_initial','2026-09-11 17:54:19.263164'),(4,'admin','0002_logentry_remove_auto_add','2026-09-11 17:54:19.265665'),(5,'admin','0003_logentry_add_action_flag_choices','2026-09-11 17:54:19.267795'),(6,'contenttypes','0002_remove_content_type_name','2026-09-11 17:54:19.281881'),(7,'auth','0002_alter_permission_name_max_length','2026-09-11 17:54:19.290015'),(8,'auth','0003_alter_user_email_max_length','2026-09-11 17:54:19.295685'),(9,'auth','0004_alter_user_username_opts','2026-09-11 17:54:19.299208'),(10,'auth','0005_alter_user_last_login_null','2026-09-11 17:54:19.306330'),(11,'auth','0006_require_contenttypes_0002','2026-09-11 17:54:19.306677'),(12,'auth','0007_alter_validators_add_error_messages','2026-09-11 17:54:19.308866'),(13,'auth','0008_alter_user_username_max_length','2026-09-11 17:54:19.317793'),(14,'auth','0009_alter_user_last_name_max_length','2026-09-11 17:54:19.326016'),(15,'auth','0010_alter_group_name_max_length','2026-09-11 17:54:19.330822'),(16,'auth','0011_update_proxy_permissions','2026-09-11 17:54:19.333311'),(17,'auth','0012_alter_user_first_name_max_length','2026-09-11 17:54:19.342063'),(18,'jobs','0001_initial','2026-09-11 17:54:19.344211'),(19,'jobs','0002_profile','2026-09-11 17:54:19.353307'),(20,'jobs','0003_profile_cv_profile_skills','2026-09-11 17:54:19.364738'),(21,'jobs','0004_profile_job_title_profile_job_type_profile_location_and_more','2026-09-11 17:54:19.386360'),(22,'jobs','0005_alter_profile_skills_cvdata','2026-09-11 17:54:19.402757'),(23,'jobs','0006_cvdata_certifications','2026-09-11 17:54:19.409003'),(24,'jobs','0007_job_savedjob','2026-09-11 17:54:19.431907'),(25,'jobs','0008_job_job_type_alter_job_source','2026-09-11 17:54:19.439785'),(26,'sessions','0001_initial','2026-09-11 17:54:19.443604'),(27,'jobs','0009_job_first_seen_at','2026-09-11 19:18:06.433523'),(28,'jobs','0010_job_category','2026-09-11 19:34:30.154806'),(29,'jobs','0011_cvdata_honours_cvdata_languages_cvdata_training_and_more','2026-09-11 20:37:41.050823'),(30,'jobs','0012_alter_profile_job_type','2026-09-11 21:19:45.045780'),(31,'jobs','0013_job_posted_by_job_salary_max_job_salary_min_and_more','2026-09-11 22:52:19.045347'),(32,'jobs','0014_alter_job_category','2026-09-11 23:22:16.680908'),(33,'jobs','0015_alter_job_source','2026-09-11 23:25:23.462458'),(34,'jobs','0016_alter_job_category','2026-09-11 23:28:22.176371'),(35,'jobs','0017_alter_job_source','2026-09-11 23:47:23.117404'),(36,'jobs','0018_scrapelock_scraperun','2026-09-12 00:03:41.636764'),(37,'jobs','0019_alter_profile_role_company_companybranch_job_branch','2026-09-13 18:34:06.355308'),(38,'jobs','0020_migrate_existing_job_posters','2026-09-13 18:45:50.159672'),(39,'jobs','0021_profile_alerts_checked_at_profile_email_job_alerts_and_more','2026-09-13 19:28:47.951927'),(40,'jobs','0022_alter_notification_options_and_more','2026-09-13 21:02:52.861799');
/*!40000 ALTER TABLE `django_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `django_content_type`
--

LOCK TABLES `django_content_type` WRITE;
/*!40000 ALTER TABLE `django_content_type` DISABLE KEYS */;
INSERT INTO `django_content_type` (`id`, `app_label`, `model`) VALUES (1,'admin','logentry'),(3,'auth','group'),(2,'auth','permission'),(4,'auth','user'),(5,'contenttypes','contenttype'),(15,'jobs','company'),(16,'jobs','companybranch'),(9,'jobs','cvdata'),(10,'jobs','job'),(17,'jobs','notification'),(8,'jobs','profile'),(11,'jobs','savedjob'),(13,'jobs','scrapelock'),(14,'jobs','scraperun'),(7,'jobs','scraperwebsite'),(12,'jobs','useractivity'),(6,'sessions','session');
/*!40000 ALTER TABLE `django_content_type` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-14  2:07:41
