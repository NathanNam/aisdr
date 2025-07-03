#!/usr/bin/env python3
"""
Test script to validate OpenTelemetry instrumentation
This script performs basic validation of the instrumentation setup
"""

import os
import sys
import logging

def test_imports():
    """Test that all OpenTelemetry modules can be imported."""
    try:
        from otel_setup import setup_observability
        from opentelemetry import trace, metrics
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        print("✅ All OpenTelemetry imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_otel_setup():
    """Test OpenTelemetry setup configuration."""
    try:
        from flask import Flask
        from otel_setup import setup_observability
        
        # Create a test Flask app
        test_app = Flask(__name__)
        
        # Set up instrumentation
        tracer, meter, custom_metrics = setup_observability(test_app)
        
        # Validate components
        assert tracer is not None, "Tracer not initialized"
        assert meter is not None, "Meter not initialized"
        assert custom_metrics is not None, "Custom metrics not initialized"
        assert len(custom_metrics) > 0, "No custom metrics created"
        
        print("✅ OpenTelemetry setup successful")
        print(f"   - Tracer: {type(tracer)}")
        print(f"   - Meter: {type(meter)}")
        print(f"   - Custom metrics: {len(custom_metrics)} metrics created")
        
        return True
    except Exception as e:
        print(f"❌ Setup error: {e}")
        return False

def test_environment():
    """Test environment variable configuration."""
    required_vars = ["SLACK_BOT_TOKEN", "OPENAI_API_KEY"]
    optional_vars = [
        "OBSERVE_INGEST_TOKEN",
        "OTEL_SERVICE_NAME",
        "OTEL_ENVIRONMENT",
        "OTEL_EXPORTER_OTLP_HEADERS",
    ]
    
    print("\n🔧 Environment Variables:")
    for var in required_vars:
        value = os.getenv(var, "NOT_SET")
        if value == "NOT_SET" or value.startswith("YOUR_"):
            print(f"   ⚠️  {var}: {value} (needs to be set)")
        else:
            print(f"   ✅ {var}: ***set***")
    
    for var in optional_vars:
        value = os.getenv(var, "NOT_SET")
        if value == "NOT_SET":
            print(f"   ℹ️  {var}: not set (optional)")
        else:
            print(f"   ✅ {var}: {value}")
    
    return True

def test_metrics_creation():
    """Test that custom metrics are properly created."""
    try:
        from otel_setup import create_custom_metrics, setup_metrics
        
        meter = setup_metrics()
        custom_metrics = create_custom_metrics(meter)
        
        expected_metrics = [
            "slack_events_counter",
            "slack_slash_commands_counter", 
            "openai_requests_counter",
            "openai_request_duration",
            "slack_messages_counter",
            "emails_generated_counter",
            "processing_errors_counter",
            "background_tasks_counter",
            "background_task_duration"
        ]
        
        for metric_name in expected_metrics:
            assert metric_name in custom_metrics, f"Missing metric: {metric_name}"
        
        print("✅ All custom metrics created successfully")
        print(f"   - Total metrics: {len(custom_metrics)}")
        
        return True
    except Exception as e:
        print(f"❌ Metrics creation error: {e}")
        return False

def main():
    """Run all validation tests."""
    print("🧪 Testing OpenTelemetry Instrumentation for AISDR")
    print("=" * 50)
    
    tests = [
        ("Import Test", test_imports),
        ("Setup Test", test_otel_setup),
        ("Environment Test", test_environment),
        ("Metrics Test", test_metrics_creation)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n📋 Running {test_name}...")
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary:")
    passed = sum(results)
    total = len(results)
    
    for i, (test_name, _) in enumerate(tests):
        status = "✅ PASS" if results[i] else "❌ FAIL"
        print(f"   {test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! OpenTelemetry instrumentation is ready.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review the configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())