"""
Database initialization and management for enterprise tools.
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

from app.config import get_settings


class DatabaseManager:
    """Manages SQLite database initialization and operations."""
    
    def __init__(self, db_path: str = None):
        settings = get_settings()
        self.db_path = db_path or settings.database.sqlite_url.replace('sqlite:///', '')
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Initialize database
        self._initialize_database()
    
    def _initialize_database(self):
        """Create all necessary tables and populate with sample data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Employees table
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id TEXT UNIQUE NOT NULL,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    department TEXT NOT NULL,
                    position TEXT NOT NULL,
                    manager_id TEXT,
                    hire_date DATE NOT NULL,
                    salary REAL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Support tickets table
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
                    requester_id TEXT NOT NULL,
                    assigned_to TEXT,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP,
                    FOREIGN KEY (requester_id) REFERENCES employees(employee_id)
                );
                
                -- Projects table
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'planning' CHECK (status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')),
                    priority TEXT DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
                    start_date DATE,
                    end_date DATE,
                    budget REAL,
                    manager_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
                );
                
                -- Expenses table
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id TEXT UNIQUE NOT NULL,
                    employee_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    expense_date DATE NOT NULL,
                    status TEXT DEFAULT 'submitted' CHECK (status IN ('submitted', 'approved', 'rejected', 'paid')),
                    approver_id TEXT,
                    receipt_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
                    FOREIGN KEY (approver_id) REFERENCES employees(employee_id)
                );
                
                -- Assets table
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    model TEXT,
                    serial_number TEXT UNIQUE,
                    purchase_date DATE,
                    purchase_cost REAL,
                    assigned_to TEXT,
                    location TEXT,
                    status TEXT DEFAULT 'available' CHECK (status IN ('available', 'assigned', 'maintenance', 'retired')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (assigned_to) REFERENCES employees(employee_id)
                );
                
                -- Training records table
                CREATE TABLE IF NOT EXISTS training_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT UNIQUE NOT NULL,
                    employee_id TEXT NOT NULL,
                    training_name TEXT NOT NULL,
                    training_type TEXT NOT NULL,
                    completion_date DATE NOT NULL,
                    expiration_date DATE,
                    score INTEGER,
                    status TEXT DEFAULT 'completed' CHECK (status IN ('enrolled', 'in_progress', 'completed', 'expired')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
                );
                
                -- Company metrics table
                CREATE TABLE IF NOT EXISTS company_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    metric_unit TEXT,
                    category TEXT NOT NULL,
                    date_recorded DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        
        # Populate with sample data
        self._populate_sample_data()
    
    def _populate_sample_data(self):
        """Populate database with realistic sample data."""
        with sqlite3.connect(self.db_path) as conn:
            # Check if data already exists
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM employees")
            if cursor.fetchone()[0] > 0:
                return  # Data already exists
            
            # Insert sample employees
            employees = [
                ('EMP001', 'John', 'Smith', 'john.smith@company.com', 'Engineering', 'Senior Software Engineer', 'EMP005', '2022-03-15', 95000, 'active'),
                ('EMP002', 'Sarah', 'Johnson', 'sarah.johnson@company.com', 'Marketing', 'Marketing Manager', 'EMP006', '2021-08-20', 75000, 'active'),
                ('EMP003', 'Mike', 'Chen', 'mike.chen@company.com', 'Finance', 'Financial Analyst', 'EMP007', '2023-01-10', 68000, 'active'),
                ('EMP004', 'Lisa', 'Williams', 'lisa.williams@company.com', 'HR', 'HR Business Partner', 'EMP008', '2020-11-05', 72000, 'active'),
                ('EMP005', 'David', 'Brown', 'david.brown@company.com', 'Engineering', 'Engineering Manager', None, '2019-06-12', 125000, 'active'),
                ('EMP006', 'Jennifer', 'Davis', 'jennifer.davis@company.com', 'Marketing', 'VP Marketing', None, '2018-03-01', 140000, 'active'),
                ('EMP007', 'Robert', 'Miller', 'robert.miller@company.com', 'Finance', 'Finance Director', None, '2019-09-15', 115000, 'active'),
                ('EMP008', 'Amanda', 'Wilson', 'amanda.wilson@company.com', 'HR', 'HR Director', None, '2017-12-01', 110000, 'active'),
                ('EMP009', 'Kevin', 'Garcia', 'kevin.garcia@company.com', 'IT', 'IT Administrator', 'EMP010', '2022-07-01', 65000, 'active'),
                ('EMP010', 'Rachel', 'Martinez', 'rachel.martinez@company.com', 'IT', 'IT Manager', None, '2020-04-15', 95000, 'active')
            ]
            
            conn.executemany("""
                INSERT INTO employees (employee_id, first_name, last_name, email, department, 
                                     position, manager_id, hire_date, salary, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, employees)
            
            # Insert sample support tickets
            tickets = [
                ('TKT001', 'Password Reset Request', 'Unable to access email account after password expiration', 'medium', 'open', 'EMP001', 'EMP009', 'IT Support'),
                ('TKT002', 'VPN Connection Issues', 'Cannot connect to company VPN from home office', 'high', 'in_progress', 'EMP002', 'EMP009', 'Network'),
                ('TKT003', 'New Employee Laptop Setup', 'Need laptop configuration for new hire starting Monday', 'medium', 'open', 'EMP004', 'EMP010', 'Hardware'),
                ('TKT004', 'Database Performance Issues', 'Customer report queries running very slowly', 'critical', 'in_progress', 'EMP005', 'EMP010', 'Database'),
                ('TKT005', 'Software License Request', 'Need Adobe Creative Suite license for marketing campaigns', 'low', 'resolved', 'EMP006', 'EMP009', 'Software'),
                ('TKT006', 'Email Phishing Report', 'Received suspicious email claiming to be from IT department', 'high', 'resolved', 'EMP003', 'EMP010', 'Security')
            ]
            
            conn.executemany("""
                INSERT INTO support_tickets (ticket_id, title, description, severity, status, 
                                           requester_id, assigned_to, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, tickets)
            
            # Insert sample projects
            projects = [
                ('PRJ001', 'Customer Portal Redesign', 'Modernize customer-facing portal with new UI/UX', 'active', 'high', '2024-01-15', '2024-06-30', 250000, 'EMP005'),
                ('PRJ002', 'Security Compliance Audit', 'SOC 2 Type II compliance preparation and audit', 'active', 'critical', '2024-02-01', '2024-04-30', 75000, 'EMP010'),
                ('PRJ003', 'Marketing Automation Platform', 'Implement new marketing automation and CRM system', 'planning', 'medium', '2024-03-01', '2024-08-31', 180000, 'EMP006'),
                ('PRJ004', 'Financial Reporting System', 'Upgrade financial reporting and analytics capabilities', 'active', 'medium', '2024-01-01', '2024-05-31', 120000, 'EMP007'),
                ('PRJ005', 'Employee Training Platform', 'Deploy comprehensive online training and certification system', 'planning', 'low', '2024-04-01', '2024-09-30', 90000, 'EMP008')
            ]
            
            conn.executemany("""
                INSERT INTO projects (project_id, name, description, status, priority, 
                                    start_date, end_date, budget, manager_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, projects)
            
            # Insert sample expenses
            expenses = [
                ('EXP001', 'EMP001', 'Travel', 450.75, 'Flight to customer site for implementation', '2024-01-15', 'approved', 'EMP005', '/receipts/exp001.pdf'),
                ('EXP002', 'EMP002', 'Marketing', 1200.00, 'Conference booth rental for industry trade show', '2024-01-20', 'paid', 'EMP006', '/receipts/exp002.pdf'),
                ('EMP003', 'EMP003', 'Office Supplies', 89.43, 'Ergonomic keyboard and mouse for workstation', '2024-01-25', 'approved', 'EMP007', '/receipts/exp003.pdf'),
                ('EXP004', 'EMP004', 'Training', 599.00, 'HR certification course enrollment fee', '2024-02-01', 'submitted', 'EMP008', '/receipts/exp004.pdf'),
                ('EXP005', 'EMP005', 'Technology', 2400.00, 'Development team laptops upgrade', '2024-02-05', 'approved', 'EMP005', '/receipts/exp005.pdf')
            ]
            
            conn.executemany("""
                INSERT INTO expenses (expense_id, employee_id, category, amount, description, 
                                    expense_date, status, approver_id, receipt_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, expenses)
            
            # Insert sample assets
            assets = [
                ('AST001', 'Dell Laptop - Engineering', 'Laptop', 'Dell XPS 15', 'DL123456789', '2023-01-15', 1899.99, 'EMP001', 'Office - Desk 15', 'assigned'),
                ('AST002', 'MacBook Pro - Marketing', 'Laptop', 'MacBook Pro 16"', 'MB987654321', '2023-02-20', 2499.99, 'EMP002', 'Office - Desk 22', 'assigned'),
                ('AST003', 'Conference Room Monitor', 'Display', 'Samsung 55" 4K', 'SM555444333', '2023-03-10', 899.99, None, 'Conference Room A', 'available'),
                ('AST004', 'Network Switch', 'Network Equipment', 'Cisco Catalyst 48-port', 'CS111222333', '2023-01-05', 1299.99, None, 'Server Room', 'assigned'),
                ('AST005', 'Printer - Finance', 'Printer', 'HP LaserJet Pro', 'HP666777888', '2023-04-12', 399.99, None, 'Finance Department', 'maintenance')
            ]
            
            conn.executemany("""
                INSERT INTO assets (asset_id, name, category, model, serial_number, purchase_date, 
                                  purchase_cost, assigned_to, location, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, assets)
            
            # Insert sample training records
            training = [
                ('TRN001', 'EMP001', 'Security Awareness Training', 'Mandatory', '2024-01-10', '2025-01-10', 95, 'completed'),
                ('TRN002', 'EMP002', 'GDPR Compliance Training', 'Compliance', '2024-01-15', '2026-01-15', 88, 'completed'),
                ('TRN003', 'EMP003', 'Financial Reporting Standards', 'Professional Development', '2024-01-20', None, 92, 'completed'),
                ('TRN004', 'EMP004', 'HR Best Practices Workshop', 'Professional Development', '2024-01-25', None, 85, 'completed'),
                ('TRN005', 'EMP005', 'Leadership Development Program', 'Leadership', '2024-02-01', None, 90, 'in_progress'),
                ('TRN006', 'EMP009', 'Cybersecurity Fundamentals', 'Technical', '2024-01-12', '2025-01-12', 94, 'completed')
            ]
            
            conn.executemany("""
                INSERT INTO training_records (record_id, employee_id, training_name, training_type, 
                                            completion_date, expiration_date, score, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, training)
            
            # Insert sample company metrics
            metrics = [
                ('Employee Count', 150, 'people', 'HR', '2024-01-31'),
                ('Revenue', 2850000, 'USD', 'Finance', '2024-01-31'),
                ('Customer Satisfaction', 4.2, 'score', 'Customer Success', '2024-01-31'),
                ('System Uptime', 99.8, 'percentage', 'IT', '2024-01-31'),
                ('Training Completion Rate', 87.5, 'percentage', 'HR', '2024-01-31'),
                ('Security Incidents', 2, 'count', 'Security', '2024-01-31'),
                ('Open Support Tickets', 23, 'count', 'IT', '2024-01-31'),
                ('Employee Retention', 94.2, 'percentage', 'HR', '2024-01-31')
            ]
            
            conn.executemany("""
                INSERT INTO company_metrics (metric_name, metric_value, metric_unit, category, date_recorded)
                VALUES (?, ?, ?, ?, ?)
            """, metrics)
            
            conn.commit()
    
    def query_sqlite(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results as dictionaries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row  # Enable column access by name
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def execute_sql(self, query: str, params: tuple = None) -> int:
        """Execute a SQL command and return number of affected rows."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            conn.commit()
            return cursor.rowcount


# Global database manager instance
database_manager = None

def get_database_manager() -> DatabaseManager:
    """Get or create the global database manager instance."""
    global database_manager
    if database_manager is None:
        database_manager = DatabaseManager()
    return database_manager