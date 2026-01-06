# Copyright (c) 2024, Nesscale Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_link_to_form

import erpnext
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)

class ExpenseEntry(Document):
	get_gl_dict = AccountsController.get_gl_dict
	get_value_in_transaction_currency = (
        AccountsController.get_value_in_transaction_currency
    )
	get_voucher_subtype = AccountsController.get_voucher_subtype


	def validate(self):
		self.calculate_totals()
		self.validate_company_in_accounting_dimension()
	
	def calculate_totals(self):
		self.total_expense = 0
		for account in self.accounts:
			self.total_expense += account.amount
	
	def on_submit(self):
		gl_entries = self.get_gl_entries()
		make_gl_entries(gl_entries)

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry",)
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def get_gl_entries(self):
		# company_currency is required by get_gl_dict
		self.company_currency = erpnext.get_company_currency(self.company)

		gl_entries = []

		for account in self.accounts:
			# Pass account item to get_gl_dict so it can pick up accounting dimensions from child table
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": account.expense_account,
						"debit": account.amount,
						"credit": 0,
						"cost_center": account.cost_center,
						"remarks": account.notes,
					},
					item=account,
				)
			)

		# Payment account entry uses dimensions from parent (self)
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.mode_of_payment_account,
					"debit": 0,
					"credit": self.total_expense,
					"remarks": self.remarks,
				},
			)
		)

		return gl_entries

	def validate_account_currency(self, account, account_currency=None):
		valid_currency = [self.company_currency]

		if account_currency not in valid_currency:
			frappe.throw(
				_("Account {0} is invalid. Account Currency must be {1}").format(
					account, (" " + _("or") + " ").join(valid_currency)
				)
			)

	def validate_company_in_accounting_dimension(self):
		"""Validate that accounting dimensions belong to the selected company"""
		if not self.company:
			return

		from frappe.query_builder import DocType

		doc_field = DocType("DocField")
		accounting_dimension = DocType("Accounting Dimension")
		dimension_list = (
			frappe.qb.from_(accounting_dimension)
			.select(accounting_dimension.document_type)
			.join(doc_field)
			.on(doc_field.parent == accounting_dimension.document_type)
			.where(doc_field.fieldname == "company")
		).run(as_list=True)

		dimension_list = sum(dimension_list, ["Project", "Cost Center"])
		accounting_dimensions = get_accounting_dimensions()

		# Validate parent document dimensions
		for dimension in accounting_dimensions:
			if self.get(dimension):
				dimension_doctype = frappe.db.get_value(
					"Accounting Dimension", {"fieldname": dimension}, "document_type"
				)
				if dimension_doctype in dimension_list:
					dimension_company = frappe.db.get_value(
						dimension_doctype, self.get(dimension), "company"
					)
					if dimension_company and dimension_company != self.company:
						frappe.throw(
							_("{0} {1} does not belong to company {2}").format(
								frappe.get_meta(dimension_doctype).get_label(),
								frappe.bold(self.get(dimension)),
								frappe.bold(self.company),
							)
						)

		# Validate child table dimensions
		for account in self.accounts:
			for dimension in accounting_dimensions:
				if account.get(dimension):
					dimension_doctype = frappe.db.get_value(
						"Accounting Dimension", {"fieldname": dimension}, "document_type"
					)
					if dimension_doctype in dimension_list:
						dimension_company = frappe.db.get_value(
							dimension_doctype, account.get(dimension), "company"
						)
						if dimension_company and dimension_company != self.company:
							frappe.throw(
								_("{0} {1} in row {2} does not belong to company {3}").format(
									frappe.get_meta(dimension_doctype).get_label(),
									frappe.bold(account.get(dimension)),
									account.idx,
									frappe.bold(self.company),
								)
							)

@frappe.whitelist()
def get_expense_type_account_and_cost_center(expense_type, company):
	data = get_expense_type_account(expense_type, company)
	cost_center = erpnext.get_default_cost_center(company)

	return {"account": data.get("account"), "cost_center": cost_center}


@frappe.whitelist()
def get_expense_type_account(expense_type, company):
	account = frappe.db.get_value(
		"Expense Type Account", {"parent": expense_type, "company": company}, "default_account"
	)
	if not account:
		frappe.throw(
			_("Set the default account for the {0} {1}").format(
				frappe.bold("Expense Type"), get_link_to_form("Expense Type", expense_type)
			)
		)

	return {"account": account}