import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserManager:
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.users_file = os.path.join(plugin_dir, "users.json")
        self.config_file = os.path.join(plugin_dir, "config.json")
        self.ensure_files()
    
    def ensure_files(self):
        """确保必要文件存在"""
        # 确保users.json存在
        if not os.path.exists(self.users_file):
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        
        # 确保config.json存在
        if not os.path.exists(self.config_file):
            default_config = {
                "admins": [],
                "reminder_enabled": True,
                "reminder_days_before": [3, 0],
                "expired_check_days": 1,
                "group_id": ""
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
    
    def load_users(self) -> Dict[str, Any]:
        """加载用户数据"""
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"加载用户数据失败: {e}")
            return {}
    
    def save_users(self, users_data: Dict[str, Any]):
        """保存用户数据"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(users_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户数据失败: {e}")
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"加载配置失败: {e}")
            return {"admins": [], "reminder_enabled": True}
    
    def save_config(self, config_data: Dict[str, Any]):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def add_or_update_user(self, user_id: str, username: str = None, extend_days: int = 0):
        """添加或更新用户信息"""
        users = self.load_users()
        
        if user_id not in users:
            # 新用户
            users[user_id] = {
                "platform_username": username or "",
                "start_date": datetime.now().strftime("%Y-%m-%d"),
                "expire_date": (datetime.now() + timedelta(days=extend_days)).strftime("%Y-%m-%d") if extend_days > 0 else datetime.now().strftime("%Y-%m-%d")
            }
        else:
            # 更新现有用户
            if username is not None:
                users[user_id]["platform_username"] = username
            if extend_days > 0:
                try:
                    current_expire = datetime.strptime(users[user_id]["expire_date"], "%Y-%m-%d")
                    # 如果当前时间已经超过到期时间，从当前时间开始计算
                    start_from = max(current_expire, datetime.now())
                    new_expire = start_from + timedelta(days=extend_days)
                    users[user_id]["expire_date"] = new_expire.strftime("%Y-%m-%d")
                except ValueError:
                    # 如果日期格式有问题，从当前时间开始
                    users[user_id]["expire_date"] = (datetime.now() + timedelta(days=extend_days)).strftime("%Y-%m-%d")
        
        self.save_users(users)
        return users[user_id]
    
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        users = self.load_users()
        return users.get(user_id)
    
    def get_users_by_expire_date(self, target_date: str) -> List[tuple]:
        """获取指定日期到期的用户"""
        users = self.load_users()
        result = []
        for user_id, user_info in users.items():
            if user_info.get("expire_date") == target_date:
                result.append((user_id, user_info))
        return result
    
    def get_expiring_users(self, days_before: int = 3) -> List[tuple]:
        """获取即将到期的用户"""
        target_date = (datetime.now() + timedelta(days=days_before)).strftime("%Y-%m-%d")
        return self.get_users_by_expire_date(target_date)
    
    def get_expired_users(self, days_after: int = 1) -> List[tuple]:
        """获取已过期的用户"""
        target_date = (datetime.now() - timedelta(days=days_after)).strftime("%Y-%m-%d")
        return self.get_users_by_expire_date(target_date)

class UserManagementPlugin:
    """用户管理插件主类"""
    
    def __init__(self, context=None, **kwargs):
        """初始化插件，兼容AstrBot的context参数"""
        self.context = context
        self.plugin_name = "用户管理插件"
        self.plugin_version = "1.0.0"
        self.plugin_description = "管理用户服务时间和自动提醒"
        
        # 获取插件目录
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.user_manager = UserManager(self.plugin_dir)
        
        # 加载配置
        self.config = self.user_manager.load_config()
        self.admins = self.config.get("admins", [])
        self.group_id = self.config.get("group_id", "")
        
        # 提醒任务状态
        self.reminder_task_running = False
        
        logger.info(f"用户管理插件已初始化，管理员: {self.admins}")
        
        # 启动提醒任务
        asyncio.create_task(self.start_reminder_task())
    
    def is_admin(self, user_id: str) -> bool:
        """检查用户是否为管理员"""
        return str(user_id) in [str(admin) for admin in self.admins]
    
    def extract_at_user(self, message_text: str) -> Optional[str]:
        """从消息中提取@的用户ID"""
        import re
        
        # 尝试匹配QQ的CQ码格式
        cq_pattern = r'\[CQ:at,qq=(\d+)\]'
        match = re.search(cq_pattern, message_text)
        if match:
            return match.group(1)
        
        # 尝试匹配其他可能的@格式
        at_pattern = r'@(\d+)'
        match = re.search(at_pattern, message_text)
        if match:
            return match.group(1)
        
        return None
    
    async def handle_yhm_command(self, message_parts: List[str], message_text: str, sender_id: str) -> str:
        """处理设置用户名指令"""
        if not self.is_admin(sender_id):
            return "❌ 权限不足，仅管理员可使用此指令"
        
        if len(message_parts) < 2:
            return "❌ 指令格式错误，请使用：/yhm [外部平台用户名] @目标用户"
        
        username = message_parts[1]
        target_user_id = self.extract_at_user(message_text)
        
        if not target_user_id:
            return "❌ 请@目标用户"
        
        try:
            user_info = self.user_manager.add_or_update_user(target_user_id, username=username)
            return f"✅ 已为用户 @{target_user_id} 设置外部平台用户名：{username}"
        except Exception as e:
            logger.error(f"设置用户名失败: {e}")
            return f"❌ 设置失败: {str(e)}"
    
    async def handle_extend_time_command(self, message_parts: List[str], message_text: str, sender_id: str) -> str:
        """处理续时指令"""
        if not self.is_admin(sender_id):
            return "❌ 权限不足，仅管理员可使用此指令"
        
        if len(message_parts) < 2:
            return "❌ 指令格式错误，请使用：/续时 [天数] @目标用户"
        
        try:
            days = int(message_parts[1])
            if days <= 0:
                return "❌ 天数必须大于0"
        except ValueError:
            return "❌ 时间长度必须是数字"
        
        target_user_id = self.extract_at_user(message_text)
        
        if not target_user_id:
            return "❌ 请@目标用户"
        
        try:
            user_info = self.user_manager.add_or_update_user(target_user_id, extend_days=days)
            return f"✅ 已为用户 @{target_user_id} 延长服务时间 {days} 天\n新的到期时间：{user_info['expire_date']}"
        except Exception as e:
            logger.error(f"续时失败: {e}")
            return f"❌ 续时失败: {str(e)}"
    
    async def handle_check_expire_command(self, sender_id: str) -> str:
        """处理查看到期时间指令"""
        user_info = self.user_manager.get_user_info(str(sender_id))
        
        if not user_info:
            return "❌ 未找到您的服务记录，请联系管理员"
        
        start_date = user_info.get("start_date", "未知")
        expire_date = user_info.get("expire_date", "未知")
        username = user_info.get("platform_username", "未设置")
        
        try:
            expire_datetime = datetime.strptime(expire_date, "%Y-%m-%d")
            today = datetime.now()
            days_left = (expire_datetime - today).days
            
            if days_left > 0:
                status_text = f"距离到期还有：{days_left} 天"
            elif days_left == 0:
                status_text = "今天到期"
            else:
                status_text = f"已过期 {abs(days_left)} 天"
        except ValueError:
            status_text = "日期格式错误"
        
        response = f"""📊 您的服务状态：
👤 外部平台用户名：{username}
📅 开户时间：{start_date}
⏰ 到期时间：{expire_date}
⏳ {status_text}"""
        
        return response
    
    async def process_message(self, message_text: str, sender_id: str, platform: str = "unknown") -> Optional[str]:
        """处理消息的主要逻辑"""
        message = message_text.strip()
        
        # 分割消息以获取指令和参数
        message_parts = message.split()
        
        if not message_parts:
            return None
        
        command = message_parts[0].lower()
        
        # 处理各种指令
        if command == "/yhm":
            return await self.handle_yhm_command(message_parts, message_text, sender_id)
        
        elif command == "/续时":
            return await self.handle_extend_time_command(message_parts, message_text, sender_id)
        
        elif command == "/查看到期时间":
            return await self.handle_check_expire_command(sender_id)
        
        # 管理员专用指令
        elif command == "/用户列表" and self.is_admin(sender_id):
            return await self.get_user_list()
        
        elif command == "/帮助":
            return self.get_help_text(sender_id)
        
        return None
    
    async def get_user_list(self) -> str:
        """获取用户列表（管理员专用）"""
        users = self.user_manager.load_users()
        
        if not users:
            return "📋 当前没有用户记录"
        
        response = "📋 用户列表：\n"
        for user_id, user_info in users.items():
            username = user_info.get("platform_username", "未设置")
            expire_date = user_info.get("expire_date", "未知")
            
            try:
                expire_datetime = datetime.strptime(expire_date, "%Y-%m-%d")
                days_left = (expire_datetime - datetime.now()).days
                
                if days_left > 0:
                    status = f"剩余{days_left}天"
                elif days_left == 0:
                    status = "今天到期"
                else:
                    status = f"已过期{abs(days_left)}天"
            except ValueError:
                status = "日期错误"
            
            response += f"\n👤 {user_id} ({username})\n   到期: {expire_date} ({status})\n"
        
        return response
    
    def get_help_text(self, sender_id: str) -> str:
        """获取帮助文本"""
        help_text = """📖 用户管理插件帮助

🔸 用户指令：
/查看到期时间 - 查看自己的服务状态
/帮助 - 显示此帮助信息"""
        
        if self.is_admin(sender_id):
            help_text += """

🔸 管理员指令：
/yhm [用户名] @用户 - 设置用户的外部平台用户名
/续时 [天数] @用户 - 为用户延长服务时间
/用户列表 - 查看所有用户列表"""
        
        return help_text
    
    async def start_reminder_task(self):
        """启动提醒任务"""
        if self.reminder_task_running:
            return
        
        self.reminder_task_running = True
        logger.info("启动自动提醒任务")
        
        while self.reminder_task_running:
            try:
                await self.check_and_send_reminders()
            except Exception as e:
                logger.error(f"提醒任务执行出错: {e}")
            
            # 每天检查一次（24小时）
            await asyncio.sleep(24 * 60 * 60)
    
    async def check_and_send_reminders(self):
        """检查并发送提醒"""
        config = self.user_manager.load_config()
        
        if not config.get("reminder_enabled", True):
            return
        
        # 检查即将到期的用户（3天前提醒）
        expiring_users_3days = self.user_manager.get_expiring_users(3)
        for user_id, user_info in expiring_users_3days:
            username = user_info.get("platform_username", "")
            message = f"⚠️ @{user_id} 您的服务将在3天后（{user_info['expire_date']}）到期，请及时续期！"
            if username:
                message += f"\n用户名：{username}"
            
            logger.info(f"发送3天到期提醒: {user_id}")
            await self.send_group_message(message)
        
        # 检查当天到期的用户
        expiring_users_today = self.user_manager.get_expiring_users(0)
        for user_id, user_info in expiring_users_today:
            username = user_info.get("platform_username", "")
            message = f"🚨 @{user_id} 您的服务今天到期（{user_info['expire_date']}），这是最后提醒！"
            if username:
                message += f"\n用户名：{username}"
            
            logger.info(f"发送当天到期提醒: {user_id}")
            await self.send_group_message(message)
        
        # 检查已过期的用户，通知管理员
        expired_users = self.user_manager.get_expired_users(1)
        for user_id, user_info in expired_users:
            username = user_info.get("platform_username", "未设置")
            message = f"🔴 管理员提醒：用户 @{user_id} (用户名: {username}) 的服务已于 {user_info['expire_date']} 到期，请及时进行关停操作。"
            
            # 私聊通知所有管理员
            for admin_id in self.admins:
                logger.info(f"发送过期通知给管理员: {admin_id}")
                await self.send_private_message(admin_id, message)
    
    async def send_group_message(self, message: str):
        """发送群消息"""
        if self.context and hasattr(self.context, 'send_message'):
            try:
                await self.context.send_message(message)
            except Exception as e:
                logger.error(f"发送群消息失败: {e}")
        else:
            logger.info(f"群消息: {message}")
    
    async def send_private_message(self, user_id: str, message: str):
        """发送私聊消息"""
        if self.context and hasattr(self.context, 'send_private_message'):
            try:
                await self.context.send_private_message(user_id, message)
            except Exception as e:
                logger.error(f"发送私聊消息失败: {e}")
        else:
            logger.info(f"私聊消息给 {user_id}: {message}")
    
    def stop_reminder_task(self):
        """停止提醒任务"""
        self.reminder_task_running = False
        logger.info("停止自动提醒任务")
    
    def get_plugin_info(self):
        """获取插件信息"""
        return {
            "name": self.plugin_name,
            "version": self.plugin_version,
            "description": self.plugin_description,
            "author": "Assistant",
            "commands": [
                "/yhm [用户名] @用户 - 设置用户名（管理员）",
                "/续时 [天数] @用户 - 延长服务时间（管理员）",
                "/查看到期时间 - 查看服务状态",
                "/用户列表 - 查看所有用户（管理员）",
                "/帮助 - 显示帮助信息"
            ]
        }
    
    def get_settings_ui(self):
        """获取设置界面数据"""
        users_data = self.user_manager.load_users()
        config_data = self.user_manager.load_config()
        
        return {
            "users_json": json.dumps(users_data, ensure_ascii=False, indent=2),
            "config": config_data,
            "stats": {
                "total_users": len(users_data),
                "active_users": len([u for u in users_data.values() 
                                   if datetime.strptime(u.get("expire_date", "1970-01-01"), "%Y-%m-%d") > datetime.now()]),
                "expired_users": len([u for u in users_data.values() 
                                    if datetime.strptime(u.get("expire_date", "1970-01-01"), "%Y-%m-%d") <= datetime.now()])
            }
        }
    
    def save_settings(self, settings_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存设置"""
        try:
            # 保存用户数据
            if "users_json" in settings_data:
                users_data = json.loads(settings_data["users_json"])
                self.user_manager.save_users(users_data)
            
            # 保存配置
            if "config" in settings_data:
                config = settings_data["config"]
                self.user_manager.save_config(config)
                
                # 更新内存中的配置
                self.config = config
                self.admins = config.get("admins", [])
                self.group_id = config.get("group_id", "")
            
            return {"success": True, "message": "设置保存成功"}
        
        except json.JSONDecodeError as e:
            return {"success": False, "message": f"JSON格式错误: {str(e)}"}
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            return {"success": False, "message": f"保存失败: {str(e)}"}

# 根据AstrBot的插件系统要求，可能需要以下方式导出插件
def register():
    """注册插件"""
    return UserManagementPlugin

# 或者直接实例化
plugin_instance = None

def get_plugin_instance(context=None):
    """获取插件实例"""
    global plugin_instance
    if plugin_instance is None:
        plugin_instance = UserManagementPlugin(context=context)
    return plugin_instance

# 兼容不同的插件加载方式
def init_plugin(context=None):
    """初始化插件"""
    return UserManagementPlugin(context=context)

# 如果直接运行此文件，进行测试
if __name__ == "__main__":
    async def test():
        # 测试基本功能
        print("=== 用户管理插件测试 ===")
        
        plugin = UserManagementPlugin()
        
        # 测试帮助指令
        result = await plugin.process_message("/帮助", "123456")
        print("帮助信息:", result)
        
        # 测试查看到期时间（无记录）
        result = await plugin.process_message("/查看到期时间", "123456")
        print("查看到期时间:", result)
        
        print("测试完成")
    
    asyncio.run(test())
