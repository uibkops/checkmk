PYTHON3_MODULES := python3-modules
PYTHON3_MODULES_VERS := $(OMD_VERSION)
PYTHON3_MODULES_DIR := $(PYTHON3_MODULES)-$(PYTHON3_MODULES_VERS)

PYTHON3_MODULES_BUILD := $(BUILD_HELPER_DIR)/$(PYTHON3_MODULES_DIR)-build
PYTHON3_MODULES_INSTALL := $(BUILD_HELPER_DIR)/$(PYTHON3_MODULES_DIR)-install
PYTHON3_MODULES_UNPACK:= $(BUILD_HELPER_DIR)/$(PYTHON3_MODULES_DIR)-unpack

.PHONY: $(PYTHON3_MODULES) $(PYTHON3_MODULES)-install $(PYTHON3_MODULES)-clean

$(PYTHON3_MODULES): $(PYTHON3_MODULES_BUILD)

$(PYTHON3_MODULES)-install: $(PYTHON3_MODULES_INSTALL)

PYTHON3_MODULES_LIST :=

PYTHON3_MODULES_LIST += setuptools_scm-3.3.3.tar.gz # needed by various setup.py
PYTHON3_MODULES_LIST += setuptools-git-1.2.tar.gz # needed by various setup.py
PYTHON3_MODULES_LIST += typing-3.7.4.tar.gz # direct dependency
PYTHON3_MODULES_LIST += six-1.12.0.tar.gz # direct dependency, indirect via python-dateutil
PYTHON3_MODULES_LIST += python-dateutil-2.8.0.tar.gz # direct dependency

$(PYTHON3_MODULES_BUILD): $(PYTHON3_BUILD) $(FREETDS_BUILD) $(PYTHON3_MODULES_UNPACK)
	set -e ; cd $(PYTHON3_MODULES_DIR) ; \
	    $(MKDIR) $(PACKAGE_PYTHON3_MODULES_PYTHONPATH) ; \
	    export PYTHONPATH="$$PYTHONPATH:$(PACKAGE_PYTHON3_MODULES_PYTHONPATH)" ; \
	    export PYTHONPATH="$$PYTHONPATH:$(PACKAGE_PYTHON3_PYTHONPATH)" ; \
	    export CPATH="$(PACKAGE_FREETDS_DESTDIR)/include" ; \
	    export LDFLAGS="$(PACKAGE_PYTHON3_LDFLAGS) $(PACKAGE_FREETDS_LDFLAGS)" ; \
	    export LD_LIBRARY_PATH="$(PACKAGE_PYTHON3_LD_LIBRARY_PATH)" ; \
	    PATH="$(abspath ./bin):$$PATH" ; \
	    for M in $(PYTHON3_MODULES_LIST); do \
		echo "Building $$M..." ; \
		PKG=$${M//.tar.gz/} ; \
		PKG=$${PKG//.zip/} ; \
		if [ $$PKG = pysnmp-git ]; then \
		    PKG=pysnmp-master ; \
		fi ; \
	    	echo $$PWD ;\
		cd $$PKG ; \
		$(PACKAGE_PYTHON3_EXECUTABLE) setup.py build ; \
		$(PACKAGE_PYTHON3_EXECUTABLE) setup.py install \
		    --root=$(PACKAGE_PYTHON3_MODULES_DESTDIR) \
		    --prefix='' \
		    --install-data=/share \
		    --install-platlib=/lib \
		    --install-purelib=/lib ; \
		cd .. ; \
	    done
	$(TOUCH) $@

$(PYTHON3_MODULES_UNPACK): $(addprefix $(PACKAGE_DIR)/$(PYTHON3_MODULES)/src/,$(PYTHON3_MODULES_LIST))
	$(RM) -r $(PYTHON3_MODULES_DIR)
	$(MKDIR) $(PYTHON3_MODULES_DIR)
	cd $(PYTHON3_MODULES_DIR) && \
	    for M in $(PYTHON3_MODULES_LIST); do \
		echo "Unpacking $$M..." ; \
		if echo $$M | grep .tar.gz; then \
		    $(TAR_GZ) $(PACKAGE_DIR)/$(PYTHON3_MODULES)/src/$$M ; \
		else \
		    $(UNZIP) $(PACKAGE_DIR)/$(PYTHON3_MODULES)/src/$$M ; \
		fi \
	    done
	$(MKDIR) $(BUILD_HELPER_DIR)
	$(TOUCH) $@

# NOTE: Setting SODIUM_INSTALL variable below is an extremely cruel hack to
# avoid installing libsodium headers and libraries. The need for this hack
# arises because of our "interesting" flag use for "setup.py install" and our
# double installation. We should really switch to e.g. pipenv here.
$(PYTHON3_MODULES_INSTALL): $(PYTHON3_MODULES_BUILD)
	$(MKDIR) $(DESTDIR)$(OMD_ROOT)/lib/python3
	set -e ; cd $(PYTHON3_MODULES_DIR) ; \
	    export SODIUM_INSTALL="system" ; \
	    export PYTHONPATH=$$PYTHONPATH:"$(PACKAGE_PYTHON3_MODULES_PYTHONPATH)" ; \
	    export PYTHONPATH=$$PYTHONPATH:"$(PACKAGE_PYTHON3_PYTHONPATH)" ; \
	    export CPATH="$(PACKAGE_FREETDS_DESTDIR)/include" ; \
	    export LDFLAGS="$(PACKAGE_PYTHON3_LDFLAGS) $(PACKAGE_FREETDS_LDFLAGS)" ; \
	    export LD_LIBRARY_PATH="$(PACKAGE_PYTHON3_LD_LIBRARY_PATH)" ; \
	    for M in $$(ls); do \
		echo "Installing $$M..." ; \
		cd $$M ; \
		$(PACKAGE_PYTHON3_EXECUTABLE) setup.py install \
		    --root=$(DESTDIR)$(OMD_ROOT) \
		    --prefix='' \
		    --install-data=/share \
		    --install-platlib=/lib/python3 \
		    --install-purelib=/lib/python3 ; \
		cd .. ; \
	    done
	$(TOUCH) $@

$(PYTHON3_MODULES)-skel:

python3-modules-dump-Pipfile:
	@echo '# ATTENTION: Most of this file is generated by omd/packages/python3-modules/python3-modules.make'
	@echo '[[source]]'
	@echo 'url = "https://pypi.python.org/simple"'
	@echo 'verify_ssl = true'
	@echo 'name = "pypi"'
	@echo ''
	@echo '[dev-packages]'
	@echo 'astroid = "*"  # used by testlib.pylint_checker_localization'
	@echo 'bandit = "*"  # used by test/Makefile'"'"'s test-bandit target'
	@echo '"beautifulsoup4" = "*"  # used by the GUI crawler and various tests'
	@echo 'bson = "*"  # used by test_mk_mongodb unit test'
	@echo 'compiledb = "*"  # used by the Livestatus/CMC Makefiles for building compile_command.json'
	@echo 'docker = "*"  # used by test_docker test and mk_docker agent plugin'
	@echo 'freezegun = "*"  # used by various unit tests'
	@echo 'isort = "*"  # used as a plugin for editors'
	@echo 'lxml = "*"  # used via beautifulsoup4 as a parser and in the agent_netapp special agent'
	@echo 'mock = "*"  # used in checktestlib in unit tests'
	@echo 'mockldap = "*"  # used in test_userdb_ldap_connector unit test'
	@echo 'pylint = "*"  # used by test/Makefile'"'"'s test-pylint target'
	@echo 'pymongo = "*"  # used by mk_mongodb agent plugin'
	@echo 'pytest = "*"  # used by various test/Makefile targets'
	@echo 'pytest-cov = "*"  # used (indirectly) by test/Makefile'"'"'s test-unit-coverage-html target, see comment there'
	@echo 'pytest-mock = "*"  # used by quite a few unit/integration tests via the mocker fixture'
	@echo 'yapf = "*"  # used for editor integration and the format-python Makefile target'
	@echo ''
	@echo '[packages]'
	@echo $(patsubst %.zip,%,$(patsubst %.tar.gz,%,$(PYTHON3_MODULES_LIST))) | tr ' ' '\n' | sed 's/-\([0-9.]*\)$$/ = "==\1"/'
	@echo ''
	@echo '[requires]'
	@echo 'python_version = "3.7"'

$(PYTHON3_MODULES)-clean:
	rm -rf $(PYTHON3_MODULES_DIR) $(BUILD_HELPER_DIR)/$(PYTHON3_MODULES)*
