#![allow(dead_code)]

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct AccountItem {
    pub name: String,
    pub email: String,
    pub alias: String,
    pub is_live: bool,
    pub is_staged: bool,
    pub is_cooldown: bool,
    pub hotkey_index: i32,
    pub is_smart_next: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QuotaData {
    pub pct_5h: f32,
    pub reset_5h: String,
    pub desc_5h: String,
    pub weekly_pct: f32,
    pub weekly_reset: String,
    pub weekly_desc: String,
    pub claude_5h_pct: f32,
    pub claude_weekly_pct: f32,
    pub tier_label: String,
    pub status_text: String,
    pub countdown_text: String,
}

impl Default for QuotaData {
    fn default() -> Self {
        Self {
            pct_5h: 100.0,
            reset_5h: "Ready".to_string(),
            desc_5h: String::new(),
            weekly_pct: 100.0,
            weekly_reset: "Ready".to_string(),
            weekly_desc: String::new(),
            claude_5h_pct: 0.0,
            claude_weekly_pct: 0.0,
            tier_label: "Pro".to_string(),
            status_text: "Available".to_string(),
            countdown_text: "Ready".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClaudeUsage {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cost_usd: f64,
    pub cache_read_tokens: u64,
    pub cache_write_tokens: u64,
}

impl Default for ClaudeUsage {
    fn default() -> Self {
        Self {
            input_tokens: 0,
            output_tokens: 0,
            cost_usd: 0.0,
            cache_read_tokens: 0,
            cache_write_tokens: 0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ClaudeStatus {
    pub detected: bool,
    pub email: String,
    pub tier_label: String,
    pub session_used_pct: f32,
    pub weekly_used_pct: f32,
    pub quota_5h_pct: f32,
    pub quota_weekly_pct: f32,
    pub reset_5h_desc: String,
    pub reset_weekly_desc: String,
    pub usage: Option<ClaudeUsage>,
}

impl Default for ClaudeStatus {
    fn default() -> Self {
        Self {
            detected: false,
            email: String::new(),
            tier_label: "Claude Pro".to_string(),
            session_used_pct: 0.0,
            weekly_used_pct: 0.0,
            quota_5h_pct: 100.0,
            quota_weekly_pct: 100.0,
            reset_5h_desc: "Ready".to_string(),
            reset_weekly_desc: "Ready".to_string(),
            usage: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DeepSeekStatus {
    pub detected: bool,
    pub signed_in: bool,
    pub email: String,
    pub balances: String,
    pub total_spend: String,
}

impl Default for DeepSeekStatus {
    fn default() -> Self {
        Self {
            detected: false,
            signed_in: false,
            email: String::new(),
            balances: "$0.00 USD".to_string(),
            total_spend: "$0.00".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FullAccountView {
    pub account: AccountItem,
    pub quota: QuotaData,
}

impl FullAccountView {
    pub fn to_slint_account_data(&self, is_selected: bool) -> crate::AccountData {
        crate::AccountData {
            id: self.account.name.clone().into(),
            alias: self.account.alias.clone().into(),
            email: self.account.email.clone().into(),
            tier: self.quota.tier_label.clone().into(),
            is_live: self.account.is_live,
            is_selected,
            session_quota_pct: self.quota.pct_5h,
            session_quota_label: format!("{:.0}%", self.quota.pct_5h).into(),
            weekly_quota_pct: self.quota.weekly_pct,
            weekly_quota_label: format!("{:.0}%", self.quota.weekly_pct).into(),
            reset_countdown: self.quota.countdown_text.clone().into(),
            status_text: self.quota.status_text.clone().into(),
        }
    }
}
