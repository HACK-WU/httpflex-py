"""
序列化器测试

测试序列化器模块的独立功能:
- BaseRequestSerializer 抽象类
- 序列化器继承和扩展
- 验证逻辑
- 错误处理
"""

import pytest
from httpflex.serializer import BaseRequestSerializer
from httpflex.exceptions import APIClientValidationError


class TestBaseRequestSerializer:
    """测试 BaseRequestSerializer 基类"""

    @pytest.mark.unit
    def test_serializer_is_abstract(self):
        """测试序列化器是抽象类"""
        # Act & Assert - 不能直接实例化
        with pytest.raises(TypeError):
            BaseRequestSerializer()

    @pytest.mark.unit
    def test_serializer_requires_validate_method(self):
        """测试序列化器要求实现 validate 方法"""

        # Arrange
        class IncompleteSerializer(BaseRequestSerializer):
            pass

        # Act & Assert
        with pytest.raises(TypeError):
            IncompleteSerializer()

    @pytest.mark.unit
    def test_serializer_with_validate_method(self):
        """测试实现了 validate 方法的序列化器"""

        # Arrange
        class CompleteSerializer(BaseRequestSerializer):
            def validate(self, data):
                return data

        # Act
        serializer = CompleteSerializer()

        # Assert
        assert serializer is not None
        assert hasattr(serializer, "validate")


class TestSerializerValidation:
    """测试序列化器验证功能"""

    @pytest.mark.unit
    def test_validate_returns_data(self):
        """测试 validate 方法返回数据"""

        # Arrange
        class SimpleSerializer(BaseRequestSerializer):
            def validate(self, data):
                return data

        serializer = SimpleSerializer()
        test_data = {"key": "value"}

        # Act
        result = serializer.validate(test_data)

        # Assert
        assert result == test_data

    @pytest.mark.unit
    def test_validate_raises_error(self):
        """测试 validate 方法抛出错误"""

        # Arrange
        class StrictSerializer(BaseRequestSerializer):
            def validate(self, data):
                if "required_field" not in data:
                    raise APIClientValidationError("required_field is missing")
                return data

        serializer = StrictSerializer()

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="required_field is missing"):
            serializer.validate({"other_field": "value"})

    @pytest.mark.unit
    def test_validate_modifies_data(self):
        """测试 validate 方法可以修改数据"""

        # Arrange
        class TransformSerializer(BaseRequestSerializer):
            def validate(self, data):
                # 将所有字符串值转换为大写
                return {k: v.upper() if isinstance(v, str) else v for k, v in data.items()}

        serializer = TransformSerializer()
        test_data = {"name": "john", "age": 25}

        # Act
        result = serializer.validate(test_data)

        # Assert
        assert result["name"] == "JOHN"
        assert result["age"] == 25


class TestSerializerInheritance:
    """测试序列化器继承"""

    @pytest.mark.unit
    def test_serializer_inheritance(self):
        """测试序列化器可以继承"""

        # Arrange
        class BaseSerializer(BaseRequestSerializer):
            def validate(self, data):
                if "base_field" not in data:
                    raise APIClientValidationError("base_field is required")
                return data

        class ExtendedSerializer(BaseSerializer):
            def validate(self, data):
                # 先调用父类验证
                data = super().validate(data)
                # 再添加额外验证
                if "extended_field" not in data:
                    raise APIClientValidationError("extended_field is required")
                return data

        serializer = ExtendedSerializer()

        # Act & Assert - 缺少 base_field
        with pytest.raises(APIClientValidationError, match="base_field is required"):
            serializer.validate({"extended_field": "value"})

        # Act & Assert - 缺少 extended_field
        with pytest.raises(APIClientValidationError, match="extended_field is required"):
            serializer.validate({"base_field": "value"})

        # Act - 所有字段都存在
        result = serializer.validate({"base_field": "value1", "extended_field": "value2"})
        assert result["base_field"] == "value1"
        assert result["extended_field"] == "value2"


class TestSerializerComplexValidation:
    """测试复杂验证场景"""

    @pytest.mark.unit
    def test_multiple_field_validation(self):
        """测试多字段验证"""

        # Arrange
        class MultiFieldSerializer(BaseRequestSerializer):
            def validate(self, data):
                errors = []
                if "username" not in data:
                    errors.append("username is required")
                if "email" not in data:
                    errors.append("email is required")
                if "age" in data and data["age"] < 0:
                    errors.append("age must be positive")

                if errors:
                    raise APIClientValidationError("; ".join(errors))
                return data

        serializer = MultiFieldSerializer()

        # Act & Assert - 多个错误
        with pytest.raises(APIClientValidationError) as exc_info:
            serializer.validate({"age": -5})
        assert "username is required" in str(exc_info.value)
        assert "email is required" in str(exc_info.value)

    @pytest.mark.unit
    def test_conditional_validation(self):
        """测试条件验证"""

        # Arrange
        class ConditionalSerializer(BaseRequestSerializer):
            def validate(self, data):
                # 如果 type 是 "premium"，则需要 payment_method
                if data.get("type") == "premium" and "payment_method" not in data:
                    raise APIClientValidationError("payment_method is required for premium type")
                return data

        serializer = ConditionalSerializer()

        # Act & Assert - premium 类型缺少 payment_method
        with pytest.raises(APIClientValidationError):
            serializer.validate({"type": "premium"})

        # Act - premium 类型有 payment_method
        result = serializer.validate({"type": "premium", "payment_method": "credit_card"})
        assert result["payment_method"] == "credit_card"

        # Act - 非 premium 类型不需要 payment_method
        result = serializer.validate({"type": "basic"})
        assert "payment_method" not in result

    @pytest.mark.unit
    def test_nested_data_validation(self):
        """测试嵌套数据验证"""

        # Arrange
        class NestedSerializer(BaseRequestSerializer):
            def validate(self, data):
                if "user" in data:
                    user = data["user"]
                    if not isinstance(user, dict):
                        raise APIClientValidationError("user must be a dict")
                    if "name" not in user:
                        raise APIClientValidationError("user.name is required")
                return data

        serializer = NestedSerializer()

        # Act & Assert - user 不是字典
        with pytest.raises(APIClientValidationError, match="user must be a dict"):
            serializer.validate({"user": "invalid"})

        # Act & Assert - user 缺少 name
        with pytest.raises(APIClientValidationError, match="user.name is required"):
            serializer.validate({"user": {"age": 25}})

        # Act - 有效的嵌套数据
        result = serializer.validate({"user": {"name": "John", "age": 25}})
        assert result["user"]["name"] == "John"


class TestSerializerDataTransformation:
    """测试数据转换功能"""

    @pytest.mark.unit
    def test_add_default_values(self):
        """测试添加默认值"""

        # Arrange
        class DefaultValueSerializer(BaseRequestSerializer):
            def validate(self, data):
                data.setdefault("status", "active")
                data.setdefault("role", "user")
                return data

        serializer = DefaultValueSerializer()

        # Act
        result = serializer.validate({"username": "john"})

        # Assert
        assert result["status"] == "active"
        assert result["role"] == "user"
        assert result["username"] == "john"

    @pytest.mark.unit
    def test_remove_extra_fields(self):
        """测试移除额外字段"""

        # Arrange
        class StrictFieldSerializer(BaseRequestSerializer):
            allowed_fields = {"username", "email", "age"}

            def validate(self, data):
                # 只保留允许的字段
                return {k: v for k, v in data.items() if k in self.allowed_fields}

        serializer = StrictFieldSerializer()

        # Act
        result = serializer.validate({"username": "john", "email": "john@example.com", "extra": "removed"})

        # Assert
        assert "username" in result
        assert "email" in result
        assert "extra" not in result

    @pytest.mark.unit
    def test_type_conversion(self):
        """测试类型转换"""

        # Arrange
        class TypeConversionSerializer(BaseRequestSerializer):
            def validate(self, data):
                # 转换字符串为整数
                if "age" in data and isinstance(data["age"], str):
                    data["age"] = int(data["age"])
                # 转换字符串为布尔值
                if "active" in data and isinstance(data["active"], str):
                    data["active"] = data["active"].lower() == "true"
                return data

        serializer = TypeConversionSerializer()

        # Act
        result = serializer.validate({"age": "25", "active": "True"})

        # Assert
        assert result["age"] == 25
        assert isinstance(result["age"], int)
        assert result["active"] is True
        assert isinstance(result["active"], bool)


class TestSerializerWithState:
    """测试带状态的序列化器"""

    @pytest.mark.unit
    def test_serializer_with_configuration(self):
        """测试带配置的序列化器"""

        # Arrange
        class ConfigurableSerializer(BaseRequestSerializer):
            def __init__(self, required_fields=None):
                self.required_fields = required_fields or []

            def validate(self, data):
                for field in self.required_fields:
                    if field not in data:
                        raise APIClientValidationError(f"{field} is required")
                return data

        serializer = ConfigurableSerializer(required_fields=["username", "email"])

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="username is required"):
            serializer.validate({"email": "john@example.com"})

        # Act
        result = serializer.validate({"username": "john", "email": "john@example.com"})
        assert result["username"] == "john"

    @pytest.mark.unit
    def test_serializer_with_counter(self):
        """测试带计数器的序列化器"""

        # Arrange
        class CountingSerializer(BaseRequestSerializer):
            def __init__(self):
                self.call_count = 0

            def validate(self, data):
                self.call_count += 1
                return data

        serializer = CountingSerializer()

        # Act
        serializer.validate({"key": "value1"})
        serializer.validate({"key": "value2"})
        serializer.validate({"key": "value3"})

        # Assert
        assert serializer.call_count == 3


class TestSerializerErrorHandling:
    """测试序列化器错误处理"""

    @pytest.mark.unit
    def test_custom_exception(self):
        """测试自定义异常"""

        # Arrange
        class CustomException(Exception):
            pass

        class ExceptionSerializer(BaseRequestSerializer):
            def validate(self, data):
                if "trigger_error" in data:
                    raise CustomException("Custom error occurred")
                return data

        serializer = ExceptionSerializer()

        # Act & Assert
        with pytest.raises(CustomException, match="Custom error occurred"):
            serializer.validate({"trigger_error": True})

    @pytest.mark.unit
    def test_exception_with_details(self):
        """测试带详细信息的异常"""

        # Arrange
        class DetailedSerializer(BaseRequestSerializer):
            def validate(self, data):
                errors = {}
                if "username" not in data:
                    errors["username"] = ["This field is required"]
                if "email" not in data:
                    errors["email"] = ["This field is required"]

                if errors:
                    # APIClientValidationError 只接受 message 参数
                    raise APIClientValidationError(f"Validation failed: {errors}")
                return data

        serializer = DetailedSerializer()

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="Validation failed"):
            serializer.validate({})


class TestSerializerEdgeCases:
    """测试边缘情况"""

    @pytest.mark.unit
    def test_empty_data(self):
        """测试空数据"""

        # Arrange
        class EmptyDataSerializer(BaseRequestSerializer):
            def validate(self, data):
                return data

        serializer = EmptyDataSerializer()

        # Act
        result = serializer.validate({})

        # Assert
        assert result == {}

    @pytest.mark.unit
    def test_none_value(self):
        """测试 None 值"""

        # Arrange
        class NoneValueSerializer(BaseRequestSerializer):
            def validate(self, data):
                # 移除值为 None 的字段
                return {k: v for k, v in data.items() if v is not None}

        serializer = NoneValueSerializer()

        # Act
        result = serializer.validate({"key1": "value", "key2": None, "key3": "another"})

        # Assert
        assert "key1" in result
        assert "key2" not in result
        assert "key3" in result

    @pytest.mark.unit
    def test_large_data(self):
        """测试大数据量"""

        # Arrange
        class LargeDataSerializer(BaseRequestSerializer):
            def validate(self, data):
                # 验证所有值都是字符串
                for key, value in data.items():
                    if not isinstance(value, str):
                        raise APIClientValidationError(f"{key} must be a string")
                return data

        serializer = LargeDataSerializer()
        large_data = {f"key_{i}": f"value_{i}" for i in range(1000)}

        # Act
        result = serializer.validate(large_data)

        # Assert
        assert len(result) == 1000

    @pytest.mark.unit
    def test_special_characters(self):
        """测试特殊字符"""

        # Arrange
        class SpecialCharSerializer(BaseRequestSerializer):
            def validate(self, data):
                return data

        serializer = SpecialCharSerializer()
        special_data = {"key": "value with 中文, emoji 😀, and symbols @#$%"}

        # Act
        result = serializer.validate(special_data)

        # Assert
        assert result["key"] == special_data["key"]
