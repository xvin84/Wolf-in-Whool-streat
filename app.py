from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import pytz
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import InputRequired, Length, Email, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from sqlalchemy import func, or_, desc, asc
from enum import Enum

date = datetime.utcnow().replace(tzinfo=pytz.UTC)
secret_key = secrets.token_hex(16)
app = Flask(__name__)
app.config['SECRET_KEY'] = secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    balance = db.relationship('Balance', back_populates='user', uselist=False)
    transactions = db.relationship('Transaction', back_populates='user')
    categories = db.relationship('UserCategory', back_populates='user')

class Balance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, default=0.0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='balance')
    transactions = db.relationship('Transaction', back_populates='balance')


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default="Без категории")
    transaction_type = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='transactions')
    balance_id = db.Column(db.Integer, db.ForeignKey('balance.id'), nullable=False)
    balance = db.relationship('Balance', back_populates='transactions')

    @staticmethod
    def after_insert(mapper, connection, target):
        if target.transaction_type == TransactionType.INCOME.value:
            target.user.balance.amount += target.amount
        elif target.transaction_type == TransactionType.EXPENSE.value:
            target.user.balance.amount -= target.amount

class UserCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', back_populates='categories')

User.categories = db.relationship('UserCategory', back_populates='user')

class TransactionType(Enum):
    INCOME = 'income'
    EXPENSE = 'expense'


with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[InputRequired(), Email()])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[InputRequired(), EqualTo('password')])
    submit = SubmitField('Зарегистрироваться')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[InputRequired(), Email()])
    password = PasswordField('Password', validators=[InputRequired()])
    submit = SubmitField('Войти')


@app.before_request
def before_request():
    # Обновляем список категорий перед каждым запросом
    g.categories = db.session.query(Transaction.category).distinct().all()
    g.categories = [category[0] for category in g.categories]


@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    current_balance = current_user.balance

    # Получаем все уникальные категории из g.categories
    all_categories = getattr(g, 'categories', [])
    transactions_query = Transaction.query.filter_by(user=current_user)
    transactions = transactions_query.all()
    return render_template('index.html', current_balance=current_balance, transactions=transactions, categories=all_categories)


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            flash('Пользователь с таким адресом электронной почты уже существует', 'error')
            return redirect(url_for('register'))
        else:
            hashed_password = generate_password_hash(form.password.data, method='scrypt')
            new_user = User(email=form.email.data, password=hashed_password, balance=Balance(amount=0.0))
            new_user.balance.user = new_user
            db.session.add(new_user)
            db.session.commit()
            flash('Ваш аккаунт успешно создан!', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            flash('Вы успешно вошли!', 'success')

            current_balance = current_user.balance
            transactions = Transaction.query.filter_by(user=current_user).all()

            return render_template('index.html', current_balance=current_balance, transactions=transactions)
        else:
            flash('Не удалось войти в аккаунт. Проверьте, правильно ли вы ввели почту и пароль', 'danger')
    return render_template('login.html', form=form)


@app.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    current_balance = current_user.balance
    all_categories = [category.name for category in current_user.categories]

    if request.method == 'POST':
        amount = float(request.form.get('add_amount'))
        category_name = request.form.get('add_category')
        transaction_type = request.form.get('add_type')

        if transaction_type == 'income':
            current_balance.amount = current_balance.amount + amount
            transaction_type_str = 'Доход'
        elif transaction_type == 'expense':
            current_balance.amount = current_balance.amount - amount
            transaction_type_str = 'Расход'

        # Проверяем, существует ли категория у текущего пользователя
        category = UserCategory.query.filter_by(name=category_name, user=current_user).first()
        if not category:
            # Если категория не существует, создаем новую
            category = UserCategory(name=category_name, user=current_user)
            db.session.add(category)

        # Создаем транзакцию
        transaction = Transaction(amount=amount, category=category_name, transaction_type=transaction_type_str, user=current_user, balance=current_user.balance)
        db.session.add(transaction)

        # Сохраняем изменения в балансе и транзакции
        db.session.commit()

        # Проверяем, была ли отправлена форма, и не сохраняем в локальное хранилище, если это не так
        if 'add_category' in request.form:
            category_input = request.form['add_category']
            # Вы можете выполнить другие действия здесь, если необходимо

        if 'add_type' in request.form:
            transaction_type_input = request.form['add_type']
            # Вы можете выполнить другие действия здесь, если необходимо
    transactions = Transaction.query.filter_by(user=current_user).all()
    return render_template('index.html', current_balance=current_balance, transactions=transactions, categories=all_categories)


@app.route('/search', methods=['POST'])
@login_required
def search():
    current_balance = current_user.balance

    # Получаем все уникальные категории текущего пользователя
    all_categories = [category.name for category in current_user.categories]

    # Получаем параметры поиска
    search_category = request.form.get('search_category')
    search_amount = request.form.get('search_amount')

    # Выполняем поиск с учетом параметров
    transactions_query = Transaction.query.filter_by(user=current_user)

    if search_category and search_category != 'all' and search_category in all_categories:
        transactions_query = transactions_query.filter_by(category=search_category)

    if search_amount:
        transactions_query = transactions_query.filter_by(amount=float(search_amount))

    transactions = transactions_query.all()

    return render_template('index.html', current_balance=current_balance, transactions=transactions, categories=all_categories)

@app.route('/sort', methods=['POST'])
@login_required
def sort():
    current_balance = current_user.balance

    # Получаем параметры сортировки
    sort_by = request.form.get('sort_by', 'date')
    sort_order = request.form.get('sort_order', 'desc')

    # Получаем все уникальные категории из g.categories
    all_categories = getattr(g, 'categories', [])

    # Выполняем сортировку с учетом параметров
    transactions_query = Transaction.query.filter_by(user=current_user)

    if sort_by == 'date':
        transactions_query = transactions_query.order_by(
            desc(Transaction.date) if sort_order == 'desc' else asc(Transaction.date))
    elif sort_by == 'amount':
        transactions_query = transactions_query.order_by(
            desc(Transaction.amount) if sort_order == 'desc' else asc(Transaction.amount))
    elif sort_by == 'category':
        transactions_query = transactions_query.order_by(
            asc(Transaction.category) if sort_order == 'asc' else desc(Transaction.category))
    elif sort_by == 'type':
        transactions_query = transactions_query.order_by(asc(Transaction.transaction_type))

    transactions = transactions_query.all()

    return render_template('index.html', current_balance=current_balance, transactions=transactions, categories=all_categories)

@app.route('/clear_history', methods=['POST'])
@login_required
def clear_history():
    transactions = Transaction.query.filter_by(user=current_user).all()
    for transaction in transactions:
        db.session.delete(transaction)
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    return redirect(url_for('index'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


db.event.listen(Transaction, 'after_insert', Transaction.after_insert)

if __name__ == '__main__':
    app.run(debug=True)
