"""账户列表查询操作 - 获取客户端所有已登录账户"""

import time

from easyths.core import BaseOperation
from easyths.core.account_state import account_state
from easyths.models.operations import EmptyParams, OperationResult
from easyths.operations.results import AccountRow, AccountsResult


class AccountQueryOperation(BaseOperation[EmptyParams]):
    """获取客户端所有已登录账户（幂等）。

    首次执行点开账户下拉，读取全部 ``(account_name, account_index)`` 条目
    并借选中项识别当前账户；此后直接复用缓存，不再触 GUI。
    """

    operation_name = "account_query"
    description = "获取客户端所有已登录账户"
    Params = EmptyParams
    Result = AccountsResult

    def execute(self, params: EmptyParams) -> OperationResult:
        start_time = time.time()
        # 幂等获取：已缓存则直接复用，不再经 GUI 实时获取
        if not account_state.available_accounts:
            entries = self._read_accounts()
            account_state.update_available_accounts(entries)
        accounts = account_state.available_accounts

        return self._ok(
            data=AccountsResult(
                available_accounts=[
                    AccountRow(account_name=name, account_index=index)
                    for name, index in accounts
                ],
            ).model_dump(),
            message=f"共{len(accounts)}个账户，耗时{time.time() - start_time:.2f}秒",
        )

    def _read_accounts(self) -> list[tuple[str, int]]:
        """从客户端读取全部账户条目，并借选中项刷新当前使用账户。

        账户名取条目完整展示名（仅去除首尾空白，如 "平安证券-王*明"），
        条目与当前使用账户使用同一清洗规则，保证后者必在可用账户列表中。
        """
        main_window = self.get_main_window(wrapper_obj=True)
        toolbar_ctl = self.get_control_with_children(
            parent_control=main_window, control_type="ToolBar", auto_id="59392"
        )
        combobox_ctl = self.get_control_with_children(
            toolbar_ctl, control_type="ComboBox", auto_id="2322"
        )

        # 9.60.81 的账户下拉是标准 ComboBox，选中项文本可由 UIA 直接读出
        # （selected_text 走 ValuePattern / SelectionPattern），无需展开下拉。
        # 这是判断"当前连的是模拟还是实盘"的关键信号，必须先拿到。
        current_name = ""
        try:
            current_name = (combobox_ctl.selected_text() or "").strip()
        except Exception as e:
            self.logger.warning("读取账户下拉选中文本失败", error=str(e))

        account_items: list[tuple[str, int]] = []
        if current_name:
            account_items.append((current_name, 1))

        # 尝试展开下拉补齐多账户列表；该客户端 9.60.81 无独立 ComboLBox 弹窗，
        # 扫描失败属正常情况，不能影响"当前账户"这一核心结果。
        try:
            dropdown_btn = self.get_control_with_children(
                combobox_ctl, control_type="Button", auto_id="DropDown"
            )
            dropdown_btn.click()
            self.sleep(0.35)
            list_boxes = self.automator.app.windows(
                class_name="ComboLBox", control_type="List"
            )
            if list_boxes:
                scanned: list[tuple[str, int]] = []
                for index, item in enumerate(list_boxes[0].children()):
                    account_name = item.window_text()
                    if account_name == "编辑账户":
                        continue
                    clean_account_name = account_name.strip()
                    if clean_account_name and (
                        clean_account_name not in [x[0] for x in scanned]
                    ):
                        scanned.append((clean_account_name, index + 1))
                if scanned:
                    account_items = scanned
                    if current_name not in [x[0] for x in account_items]:
                        account_items.insert(0, (current_name, 1))
            main_window.type_keys("{ESC}")
        except Exception as e:
            self.logger.warning("账户下拉扫描失败，仅使用当前账户", error=str(e))
            try:
                main_window.type_keys("{ESC}")
            except Exception:
                pass

        if not account_items:
            raise RuntimeError("无法从客户端读取账户信息（下拉文本为空）")

        # 当前账户以 UIA 选中文本为准（下拉列表顺序 ≠ 当前选中项）
        effective_current = current_name or account_items[0][0]
        account_state.set_current_used_account(effective_current)
        self.logger.info(f"当前使用的账户为：{effective_current}")
        return account_items
