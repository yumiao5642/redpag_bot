USE rebpag_data;

-- 用户表
CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY, -- Telegram 用户ID
  username VARCHAR(64),
  first_name VARCHAR(64),
  last_name VARCHAR(64),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  tx_password_hash VARCHAR(128) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户钱包（TRC20）
CREATE TABLE IF NOT EXISTS user_wallets (
  user_id BIGINT NOT NULL,
  usdt_trc20_balance DECIMAL(18,6) NOT NULL DEFAULT 0,
  tron_address VARCHAR(64) UNIQUE,
  tron_privkey_enc TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  CONSTRAINT fk_wallet_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 红包
CREATE TABLE IF NOT EXISTS red_packets (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  owner_id BIGINT NOT NULL,
  type ENUM('random','average','exclusive') NOT NULL,
  currency VARCHAR(32) NOT NULL DEFAULT 'USDT-trc20',
  total_amount DECIMAL(18,6) NOT NULL,
  count INT NOT NULL DEFAULT 1,
  cover_text VARCHAR(150) DEFAULT NULL,
  cover_image_file_id VARCHAR(128) DEFAULT NULL,
  exclusive_user_id BIGINT DEFAULT NULL,
  status ENUM('created','paid','sent','finished','expired','cancelled') NOT NULL DEFAULT 'created',
  chat_id BIGINT DEFAULT NULL,
  message_id BIGINT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NULL DEFAULT NULL,
  CONSTRAINT fk_redpacket_user FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 红包拆分份额（预先生成）
CREATE TABLE IF NOT EXISTS red_packet_shares (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  red_packet_id BIGINT NOT NULL,
  seq INT NOT NULL,
  amount DECIMAL(18,6) NOT NULL,
  claimed_by BIGINT DEFAULT NULL,
  claimed_at TIMESTAMP NULL DEFAULT NULL,
  UNIQUE KEY uq_packet_seq (red_packet_id, seq),
  CONSTRAINT fk_share_packet FOREIGN KEY (red_packet_id) REFERENCES red_packets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 红包领取记录（冗余）
CREATE TABLE IF NOT EXISTS red_packet_claims (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  red_packet_id BIGINT NOT NULL,
  claimer_id BIGINT NOT NULL,
  amount DECIMAL(18,6) NOT NULL,
  claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_claim_packet FOREIGN KEY (red_packet_id) REFERENCES red_packets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 充值订单
CREATE TABLE IF NOT EXISTS recharge_orders (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  address VARCHAR(64) NOT NULL,
  status ENUM('waiting','collecting','verifying','success','expired','failed') NOT NULL DEFAULT 'waiting',
  expected_amount DECIMAL(18,6) DEFAULT NULL,
  txid_collect VARCHAR(128) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expire_at TIMESTAMP NULL DEFAULT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_recharge_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 账变流水
CREATE TABLE IF NOT EXISTS ledger (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  change_type ENUM('recharge','withdraw','redpacket_send','redpacket_claim','adjust') NOT NULL,
  amount DECIMAL(18,6) NOT NULL,
  balance_before DECIMAL(18,6) NOT NULL,
  balance_after DECIMAL(18,6) NOT NULL,
  ref_type VARCHAR(32) DEFAULT NULL,
  ref_id BIGINT DEFAULT NULL,
  remark VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ledger_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 常用地址
CREATE TABLE IF NOT EXISTS user_addresses (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  chain VARCHAR(16) NOT NULL DEFAULT 'TRX',
  address VARCHAR(64) NOT NULL,
  alias VARCHAR(32) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_addr (user_id, address),
  CONSTRAINT fk_addr_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_rent_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  address VARCHAR(50) NOT NULL,
  order_id BIGINT NULL,
  order_no VARCHAR(32) NULL,
  provider VARCHAR(32) NOT NULL DEFAULT 'trongas',
  rent_order_id VARCHAR(64) NULL,
  rent_txid VARCHAR(100) NULL,
  rented_at DATETIME NOT NULL,
  expire_at DATETIME NOT NULL,
  status ENUM('active','used','expired','failed') NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_energy_addr (address, status, expire_at)
);

ALTER TABLE recharge_orders
  ADD COLUMN txid VARCHAR(100) NULL AFTER status,
  ADD COLUMN updated_at DATETIME NULL AFTER expire_at;

-- 扫描 waiting 过期单用到的索引
CREATE INDEX idx_recharge_waiting ON recharge_orders (status, expire_at);


-- 增加来源表名/来源ID（若已存在会报重复，直接忽略提示即可）
ALTER TABLE ledger
  ADD COLUMN ref_table VARCHAR(32) NULL AFTER change_type,
  ADD COLUMN ref_id INT NULL AFTER ref_table;

-- 幂等索引（重复则忽略即可）
CREATE INDEX idx_ledger_ref ON ledger (change_type, ref_table, ref_id);

-- 系统开关表
CREATE TABLE IF NOT EXISTS sys_flags (
  k VARCHAR(64) PRIMARY KEY,
  v VARCHAR(255) NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 初始不锁
INSERT IGNORE INTO sys_flags(k, v) VALUES ('lock_withdraw', '0'), ('lock_redpacket', '0');
