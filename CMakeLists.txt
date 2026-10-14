cmake_minimum_required(VERSION 3.8)
project(letssee)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/Generate.srv" "srv/GenerateText.srv" "srv/AnalyzeImage.srv"
  DEPENDENCIES sensor_msgs)
ament_export_dependencies(rosidl_default_runtime)

# Install separately from the generated Python interface package.
ament_get_python_install_dir(PYTHON_INSTALL_DIR)
install(DIRECTORY letssee_llm DESTINATION ${PYTHON_INSTALL_DIR}
  PATTERN "__pycache__" EXCLUDE)
install(PROGRAMS scripts/llm_service scripts/generate_text_service
  scripts/vlm_service scripts/download_models DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY prompts schemas launch DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE)
# Weight folders stay local; only the registry is installed.
install(FILES models/model_library.yaml DESTINATION share/${PROJECT_NAME}/models)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  set(LLM_TEST_PYTHON "${Python3_EXECUTABLE}" CACHE FILEPATH
    "Python interpreter for model tests (may be a ROS-compatible virtual environment)")
  ament_add_pytest_test(local_llm test
    PYTHON_EXECUTABLE "${LLM_TEST_PYTHON}"
    TIMEOUT 180
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR})
endif()

ament_package()
